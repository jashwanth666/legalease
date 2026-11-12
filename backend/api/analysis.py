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
    risks = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.document_id == doc.document_id)
        .order_by(RiskAssessment.risk_score.desc())
        .all()
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

    counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    risk_items = []
    for r in risks:
        counts[r.risk_level] = counts.get(r.risk_level, 0) + 1
        risk_items.append(
            {
                "clause_id": r.clause_id,
                "clause_title": clause_title_map.get(r.clause_id, r.clause_id),
                "category": clause_cat_map.get(r.clause_id, "Other"),
                "risk_level": r.risk_level,
                "risk_score": r.risk_score,
                "risk_title": r.risk_title or f"{r.risk_level.title()} risk finding",
                "original_clause": clause_text_map.get(r.clause_id, ""),
                "explanation": r.explanation,
                "potential_impact": r.potential_impact or "",
                "suggested_action": r.suggested_action or "",
                "page_number": r.page_number,
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
    overall_level = doc.overall_risk_level or classify_risk_level(overall_score)

    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "processing_status": doc.processing_status,
        "detected_contract_type": doc.detected_contract_type,
        "analysis_mode": doc.analysis_mode or "deterministic_fallback",
        "overall_risk_score": overall_score,
        "overall_risk_level": overall_level,
        "risk_distribution": {
            "low": counts["low"],
            "medium": counts["medium"],
            "high": counts["high"],
            "critical": counts["critical"],
            "total": len(clauses),
        },
        "executive_summary": doc.executive_summary or "",
        "risk_findings": risk_items,
        "missing_clauses": missing_clauses,
        "comparison_count": len(comparisons),
        "report_available": report is not None,
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

    if doc.ocr_required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No usable selectable text was detected in this document. "
                "OCR is required before automated analysis."
            ),
        )

    file_path = settings.upload_dir / doc.stored_filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document binary is missing for '{document_id}'.",
        )

    doc.processing_status = "processing"
    db.commit()

    runtime_config = {
        "gemini_api_key": settings.gemini_api_key,
        "gemini_model": settings.gemini_model,
        "extracted_dir": str(settings.extracted_dir),
        "vectorstore_dir": str(settings.vectorstore_dir),
        "templates_dir": str(settings.reference_templates_dir),
        "reports_dir": str(settings.reports_dir),
    }

    result_state = run_contract_analysis(
        document_id=doc.document_id,
        filename=doc.filename,
        file_path=str(file_path),
        file_type=doc.file_type,
        runtime_config=runtime_config,
    )

    errors = result_state.get("processing_errors") or []
    if errors:
        doc.processing_status = "ocr_required" if result_state.get("ocr_required") else "failed"
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
            }
            for c in clauses
        ],
    }

