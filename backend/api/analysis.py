"""Contract analysis execution, retrieval, and clause listing endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.config import LEGAL_DISCLAIMER, Settings, get_settings
from backend.database import (
    AnalysisReport,
    Clause,
    Comparison,
    Document,
    RiskAssessment,
    User,
    get_db,
)
from backend.database.db import SessionLocal
from backend.graph.nodes import ALL_WORKFLOW_STAGES
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

    contract_metadata = {}
    if doc.metadata_json:
        try:
            contract_metadata = json.loads(doc.metadata_json)
        except json.JSONDecodeError:
            contract_metadata = {}

    overall_score = doc.overall_risk_score if doc.overall_risk_score is not None else 0.0
    overall_level = doc.overall_risk_level or (
        "no_notable_risk" if scored_clauses == 0 else classify_risk_level(overall_score)
    )

    ver_risks = sum(1 for r in risks if r.verified)
    unver_risks = len(risks) - ver_risks
    ver_comps = sum(1 for c in comparisons if not getattr(c, "insufficient_evidence", False) and getattr(c, "verified", True))
    unver_comps = len(comparisons) - ver_comps

    total_meta = 0
    ver_meta = 0
    if contract_metadata and isinstance(contract_metadata, dict):
        for k, v in contract_metadata.items():
            if isinstance(v, dict) and k not in ("document_id", "extraction_source", "completeness_score") and not v.get("is_missing"):
                total_meta += 1
                if v.get("verified"):
                    ver_meta += 1
    unver_meta = total_meta - ver_meta

    ms_cats = missing_clauses.get("missing_categories", []) if isinstance(missing_clauses, dict) else []
    ver_missing = sum(1 for m in ms_cats if m.get("verified", True))
    unver_missing = len(ms_cats) - ver_missing

    total_findings = len(risks) + len(comparisons) + total_meta + len(ms_cats)
    total_verified = ver_risks + ver_comps + ver_meta + ver_missing
    total_unverified = unver_risks + unver_comps + unver_meta + unver_missing
    all_ver = (total_unverified == 0) if total_findings > 0 else True

    verification_summary = {
        "all_verified": all_ver,
        "total_findings": total_findings,
        "total_verified": total_verified,
        "total_unverified": total_unverified,
        "verification_rate_percent": round((total_verified / total_findings * 100), 1) if total_findings > 0 else 100.0,
        "risks": {"total": len(risks), "verified": ver_risks, "unverified": unver_risks},
        "comparisons": {"total": len(comparisons), "verified": ver_comps, "unverified": unver_comps},
        "metadata": {"total": total_meta, "verified": ver_meta, "unverified": unver_meta},
        "missing_clauses": {"total": len(ms_cats), "verified": ver_missing, "unverified": unver_missing},
    }

    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "page_count": doc.page_count,
        "processing_status": doc.processing_status,
        "current_stage": doc.current_stage or doc.processing_status,
        "progress_percent": doc.progress_percent if doc.progress_percent is not None else 0,
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
        "contract_metadata": contract_metadata,
        "comparison_count": len(comparisons),
        "report_available": report is not None and doc.processing_status == "analyzed",
        "report_path": report.report_path if report else "",
        "verified_findings": {
            "all_verified": all_ver,
            "total_audited": total_findings,
            "total_verified": total_verified,
            "total_unverified": total_unverified,
            "verified_risk_count": ver_risks,
            "verified_comparison_count": ver_comps,
            "verified_metadata_count": ver_meta,
            "verified_missing_clauses_count": ver_missing,
        },
        "verification_summary": verification_summary,
        "disclaimer": LEGAL_DISCLAIMER,
    }


def run_contract_analysis_task(document_id: str, settings: Settings) -> None:
    """Isolated background task execution for contract analysis with dedicated DB session."""
    from backend.database import db as db_module
    db_session = db_module.SessionLocal()
    try:
        doc = db_session.query(Document).filter(Document.document_id == document_id).first()
        if not doc:
            logger.error("Background task: document %s not found in DB", document_id)
            return

        tenant_id = doc.tenant_id or "default_tenant"
        tenant_upload = settings.upload_dir / tenant_id / doc.stored_filename
        file_path = tenant_upload if tenant_upload.exists() else (settings.upload_dir / doc.stored_filename)

        if not file_path.exists():
            doc.processing_status = "failed"
            doc.current_stage = "failed"
            doc.last_error = f"Stored document binary is missing for '{document_id}'."
            db_session.commit()
            return

        doc.processing_status = "processing"
        doc.current_stage = "document_validation"
        doc.progress_percent = 8
        doc.last_error = None
        db_session.commit()

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
            errors = result_state.get("processing_errors") or []
            db_session.expire_all()
            target_doc = db_session.query(Document).filter(Document.document_id == document_id).first()
            if target_doc is not None:
                if errors:
                    if result_state.get("db_saved") and not result_state.get("pdf_generated"):
                        target_doc.processing_status = "partially_analyzed"
                        target_doc.current_stage = "partially_analyzed"
                    else:
                        target_doc.processing_status = "failed"
                        target_doc.current_stage = "failed"
                    target_doc.last_error = "; ".join(errors)[:500]
                else:
                    if target_doc.processing_status != "analyzed":
                        target_doc.processing_status = "analyzed"
                    target_doc.current_stage = "completed"
                    target_doc.progress_percent = 100
                    target_doc.last_error = None
                db_session.commit()
        except Exception as exc:
            db_session.rollback()
            safe_msg = f"Workflow error ({type(exc).__name__}). Please verify configuration and retry."
            logger.exception("Background contract analysis workflow crashed for document_id=%s", document_id)
            target_doc = db_session.query(Document).filter(Document.document_id == document_id).first()
            if target_doc is not None:
                target_doc.processing_status = "failed"
                target_doc.current_stage = "failed"
                target_doc.last_error = safe_msg
                db_session.commit()
    finally:
        db_session.close()


@router.post("/analyze/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def analyze_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
    wait: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Run the contract analysis pipeline asynchronously with tenant isolation and concurrency controls."""
    doc = db.query(Document).filter(
        Document.document_id == document_id,
        Document.tenant_id == current_user.tenant_id,
    ).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    # Role check: employee can only analyze documents they own
    if current_user.role == "employee" and doc.owner_id is not None and doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employees may only analyze their own documents.",
        )

    tenant_id = doc.tenant_id or "default_tenant"
    tenant_upload = settings.upload_dir / tenant_id / doc.stored_filename
    file_path = tenant_upload if tenant_upload.exists() else (settings.upload_dir / doc.stored_filename)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document binary is missing for '{document_id}'.",
        )

    # Concurrency control: atomic compare-and-swap (CAS) job claiming
    # Only transitions to 'queued' if the document is NOT already in ('queued', 'processing')
    claimed_count = (
        db.query(Document)
        .filter(
            Document.document_id == document_id,
            Document.tenant_id == current_user.tenant_id,
            Document.processing_status.notin_(["queued", "processing"]),
        )
        .update(
            {
                Document.processing_status: "queued",
                Document.current_stage: "queued",
                Document.progress_percent: 5,
                Document.completed_stages_json: "[]",
                Document.last_error: None,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()

    if claimed_count == 0:
        db.expire_all()
        refreshed_doc = db.query(Document).filter(
            Document.document_id == document_id,
            Document.tenant_id == current_user.tenant_id,
        ).first()
        active_status = refreshed_doc.processing_status if refreshed_doc else "processing"
        active_stage = refreshed_doc.current_stage if refreshed_doc else "queued"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{document_id}' is already being analyzed (status: {active_status}, stage: {active_stage}). Please wait for the current analysis to complete.",
        )

    if wait:
        run_contract_analysis_task(document_id, settings)
        db.expire_all()
        refreshed = db.query(Document).filter(Document.document_id == document_id).first()
        if not refreshed:
            raise HTTPException(status_code=404, detail="Document disappeared during analysis.")
        if refreshed.processing_status == "failed":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=refreshed.last_error or "Contract analysis failed.",
            )
        if response is not None:
            response.status_code = status.HTTP_200_OK
        return _build_analysis_payload(refreshed, db)

    background_tasks.add_task(run_contract_analysis_task, document_id, settings)
    return {
        "document_id": document_id,
        "processing_status": "queued",
        "current_stage": "queued",
        "progress_percent": 5,
        "message": f"Contract analysis for '{document_id}' has been queued as a background task.",
    }


@router.get("/status/{document_id}")
def get_analysis_status(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return real-time contract processing status, pipeline progress, completed stages, and error details."""
    doc = db.query(Document).filter(
        Document.document_id == document_id,
        Document.tenant_id == current_user.tenant_id,
    ).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    stage_display_names = {
        "uploaded": "Ready for analysis",
        "ocr_required": "OCR required",
        "queued": "Queued in background",
        "document_validation": "Validating document integrity",
        "text_extraction": "Extracting text and layout",
        "ocr": "Running optical character recognition",
        "clause_splitting": "Segmenting legal clauses",
        "clause_classification": "Classifying clause categories",
        "risk_assessment": "Assessing liability and risk exposure",
        "template_comparison": "Comparing against reference templates",
        "missing_clause_detection": "Evaluating mandatory clause checklist",
        "metadata_extraction": "Extracting structured contract metadata",
        "evidence_verification": "Verifying grounded source citations",
        "summary_generation": "Generating executive summary",
        "pdf_generation": "Building PDF intelligence report",
        "partially_analyzed": "Analysis complete, report generation pending",
        "completed": "Analysis complete",
        "analyzed": "Completed",
        "failed": "Analysis failed",
    }

    try:
        completed_stages = json.loads(doc.completed_stages_json or "[]")
    except Exception:
        completed_stages = []

    pending_stages = [s for s in ALL_WORKFLOW_STAGES if s not in completed_stages]
    current_stage = doc.current_stage or doc.processing_status
    progress_percent = doc.progress_percent if doc.progress_percent is not None else 0
    if doc.processing_status == "analyzed":
        progress_percent = 100
        pending_stages = []

    has_report = len(doc.reports) > 0
    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "processing_status": doc.processing_status,
        "current_stage": current_stage,
        "stage": stage_display_names.get(current_stage, current_stage.replace("_", " ").title()),
        "progress_percent": progress_percent,
        "completed_stages": completed_stages,
        "pending_stages": pending_stages,
        "last_error": doc.last_error,
        "detected_contract_type": doc.detected_contract_type,
        "overall_risk_score": doc.overall_risk_score,
        "overall_risk_level": doc.overall_risk_level,
        "report_available": has_report,
    }


@router.get("/analysis/{document_id}")
def get_analysis(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve stored contract analysis results from SQLite with tenant verification."""
    doc = db.query(Document).filter(
        Document.document_id == document_id,
        Document.tenant_id == current_user.tenant_id,
    ).first()
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
def get_clauses(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve extracted and classified clauses for a document with tenant verification."""
    doc = db.query(Document).filter(
        Document.document_id == document_id,
        Document.tenant_id == current_user.tenant_id,
    ).first()
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


@router.get("/metadata/{document_id}")
def get_contract_metadata(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve structured 16-field contract metadata with grounded evidence."""
    doc = db.query(Document).filter(
        Document.document_id == document_id,
        Document.tenant_id == current_user.tenant_id,
    ).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    if doc.processing_status not in ("analyzed", "partially_analyzed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{document_id}' has not been analyzed yet (status: {doc.processing_status}).",
        )

    metadata = {}
    if doc.metadata_json:
        try:
            metadata = json.loads(doc.metadata_json)
        except json.JSONDecodeError:
            metadata = {}

    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "contract_type": doc.detected_contract_type,
        "metadata": metadata,
    }


