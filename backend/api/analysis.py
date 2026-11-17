"""Contract analysis execution, retrieval, and clause listing endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config import LEGAL_DISCLAIMER, Settings, get_settings
from backend.database import (
    AnalysisReport,
    Clause,
    Comparison,
    Document,
    RiskAssessment,
    get_db,
)
from backend.graph.workflow import run_contract_analysis
from backend.services.scoring_service import classify_risk_level


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Analysis"])


def _build_analysis_payload(doc: Document, db: Session) -> dict[str, Any]:
    clauses = (
        db.query(Clause)
        .filter(Clause.document_id == doc.document_id)
        .order_by(Clause.clause_id.asc())
        .all()
    )
    risks = sorted(
        db.query(RiskAssessment).filter(RiskAssessment.document_id == doc.document_id).all(),
        key=lambda r: (r.risk_score if r.risk_score is not None else -1.0),
        reverse=True,
    )
    comparisons = (
        db.query(Comparison)
        .filter(Comparison.document_id == doc.document_id)
        .order_by(Comparison.clause_id.asc())
        .all()
    )
    report = (
        db.query(AnalysisReport)
        .filter(AnalysisReport.document_id == doc.document_id)
        .order_by(AnalysisReport.created_at.desc())
        .first()
    )

    clause_text_map = {c.clause_id: c.original_text for c in clauses}
    clause_title_map = {c.clause_id: c.title for c in clauses}
    clause_cat_map = {c.clause_id: c.category for c in clauses}

    counts = {
        "no_notable_risk": 0,
        "uncertain": 0,
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
    }
    scored_clauses = 0
    risk_items = []
    for r in risks:
        if r.finding_type in ("uncertain_finding", "missing_information") or r.risk_level == "uncertain":
            counts["uncertain"] += 1
        elif r.finding_type == "no_notable_risk" or r.risk_score is None:
            counts["no_notable_risk"] += 1
        else:
            lvl = r.risk_level if r.risk_level in ("low", "medium", "high", "critical") else classify_risk_level(r.risk_score)
            counts[lvl] += 1
            scored_clauses += 1

        risk_items.append(
            {
                "clause_id": r.clause_id,
                "clause_title": clause_title_map.get(r.clause_id, r.clause_id),
                "category": clause_cat_map.get(r.clause_id, "Other"),
                "risk_level": r.risk_level,
                "risk_score": r.risk_score,
                "risk_title": r.risk_title or f"{r.risk_level.replace('_', ' ').title()}",
                "original_clause": clause_text_map.get(r.clause_id, ""),
                "explanation": r.explanation,
                "potential_impact": r.potential_impact or "",
                "suggested_action": r.suggested_action or "",
                "page_number": r.page_number,
                "location_type": r.location_type or ("docx_paragraph" if r.page_number is None else "pdf_page"),
                "paragraph_index": r.paragraph_index,
                "section_title": r.section_title,
                "verified": r.verified,
                "finding_type": r.finding_type,
            }
        )

    missing_clauses = {}
    if doc.missing_clauses_json:
        try:
            missing_clauses = json.loads(doc.missing_clauses_json)
        except json.JSONDecodeError:
            missing_clauses = {}

    overall_score = doc.overall_risk_score if doc.overall_risk_score is not None else 0.0
    overall_level = doc.overall_risk_level or (
        "no_notable_risk" if scored_clauses == 0 else classify_risk_level(overall_score)
    )

    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "processing_status": doc.processing_status,
        "detected_contract_type": doc.detected_contract_type,
        "analysis_mode": doc.analysis_mode or "deterministic_fallback",
        "gemini_status": doc.gemini_status or "missing_key",
        "fallback_used": bool(doc.fallback_used),
        "fallback_reason": doc.fallback_reason,
        "embedding_backend": doc.embedding_backend or "deterministic_hash",
        "last_error": doc.last_error,
        "overall_risk_score": overall_score,
        "overall_risk_level": overall_level,
        "scoring_limitations": (
            "Overall score blends peak detected clause exposure and contract-wide flagged risk density. "
            "Clauses without notable risk patterns or with uncertain wording are not given numeric safety scores; "
            "a low score never proves a contract is legally safe."
        ),
        "risk_distribution": {
            "no_notable_risk": counts["no_notable_risk"],
            "uncertain": counts["uncertain"],
            "low": counts["low"],
            "medium": counts["medium"],
            "high": counts["high"],
            "critical": counts["critical"],
            "scored_clauses": scored_clauses,
            "total": len(clauses),
        },
        "executive_summary": doc.executive_summary or "",
        "risk_findings": risk_items,
        "missing_clauses": missing_clauses,
        "comparison_count": len(comparisons),
        "report_available": report is not None and doc.processing_status == "analyzed",
        "disclaimer": LEGAL_DISCLAIMER,
    }


@router.post("/analyze/{document_id}")
def analyze_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Run the full LangGraph analysis pipeline for an already-uploaded contract."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    file_path = settings.upload_dir / doc.stored_filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document binary is missing for '{document_id}'.",
        )

    doc.processing_status = "processing"
    doc.last_error = None
    db.commit()

    runtime_config = {
        "gemini_api_key": settings.gemini_api_key,
        "gemini_model": settings.gemini_model,
        "extracted_dir": str(settings.extracted_dir),
        "vectorstore_dir": str(settings.vectorstore_dir),
        "templates_dir": str(settings.reference_templates_dir),
        "reports_dir": str(settings.reports_dir),
    }

    try:
        result_state = run_contract_analysis(
            document_id=doc.document_id,
            filename=doc.filename,
            file_path=str(file_path),
            file_type=doc.file_type,
            runtime_config=runtime_config,
        )
    except Exception as exc:
        db.rollback()
        safe_msg = f"Workflow error ({type(exc).__name__}). Please verify configuration and retry."
        logger.exception("Contract analysis workflow crashed for document_id=%s", document_id)
        failed_doc = db.query(Document).filter(Document.document_id == document_id).first()
        if failed_doc is not None:
            failed_doc.processing_status = "failed"
            failed_doc.last_error = safe_msg
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_msg,
        ) from exc

    errors = result_state.get("processing_errors") or []
    if errors:
        if result_state.get("db_saved") and not result_state.get("pdf_generated"):
            next_status = "partially_analyzed"
        else:
            next_status = "failed"

        db.expire_all()
        target_doc = db.query(Document).filter(Document.document_id == document_id).first()
        if target_doc is not None:
            target_doc.processing_status = next_status
            target_doc.last_error = "; ".join(errors)[:500]
            db.commit()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="; ".join(errors),
        )

    db.expire_all()
    refreshed = db.query(Document).filter(Document.document_id == document_id).first()
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Document disappeared during analysis.")

    payload = _build_analysis_payload(refreshed, db)
    payload["verified_findings"] = result_state.get("verified_findings", {})
    payload["report_path"] = result_state.get("report_path", "")
    return payload


@router.get("/analysis/{document_id}")
def get_analysis(document_id: str, db: Session = Depends(get_db)):
    """Retrieve stored contract analysis results from SQLite."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    if doc.processing_status != "analyzed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{document_id}' has not been analyzed yet (status: {doc.processing_status}).",
        )

    return _build_analysis_payload(doc, db)


@router.get("/clauses/{document_id}")
def get_clauses(document_id: str, db: Session = Depends(get_db)):
    """Retrieve extracted and classified clauses for a document."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    clauses = (
        db.query(Clause)
        .filter(Clause.document_id == document_id)
        .order_by(Clause.clause_id.asc())
        .all()
    )

    return {
        "document_id": document_id,
        "filename": doc.filename,
        "processing_status": doc.processing_status,
        "count": len(clauses),
        "clauses": [
            {
                "clause_id": c.clause_id,
                "title": c.title,
                "category": c.category,
                "description": c.description or "",
                "confidence": c.confidence,
                "classification_source": c.classification_source or "deterministic_fallback",
                "original_text": c.original_text,
                "page_number": c.page_number,
                "end_page_number": c.end_page_number,
                "location_type": c.location_type or ("docx_paragraph" if c.page_number is None else "pdf_page"),
                "paragraph_index": c.paragraph_index,
                "section_title": c.section_title,
                "segmentation_confidence": c.segmentation_confidence or "high",
                "segmentation_uncertain": bool(c.segmentation_uncertain),
            }
            for c in clauses
        ],
    }

