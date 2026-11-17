"""PDF analysis report download and listing endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database import (
    AnalysisReport,
    Clause,
    Comparison,
    Document,
    RiskAssessment,
    get_db,
)
from backend.guardrails.document_guard import DocumentValidationError, resolve_contained_path
from backend.services.pdf_service import generate_analysis_pdf
from backend.services.scoring_service import classify_risk_level


router = APIRouter(prefix="/api", tags=["Reports"])


@router.get("/reports")
def list_reports(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """List generated analysis reports ordered newest first."""
    reports = (
        db.query(AnalysisReport, Document)
        .join(Document, AnalysisReport.document_id == Document.document_id)
        .filter(Document.processing_status == "analyzed")
        .order_by(AnalysisReport.created_at.desc())
        .all()
    )
    items = []
    for rep, doc in reports:
        try:
            contained = resolve_contained_path(settings.reports_dir, Path(rep.report_path))
            exists = contained.exists() and contained.stat().st_size > 0
        except (DocumentValidationError, OSError):
            exists = False
        items.append(
            {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "detected_contract_type": doc.detected_contract_type,
                "overall_risk_score": doc.overall_risk_score,
                "overall_risk_level": doc.overall_risk_level,
                "report_exists": exists,
                "file_ok": exists,
                "created_at": rep.created_at,
            }
        )
    return items


@router.get("/report/{document_id}")
@router.get("/reports/{document_id}/download")
def download_report(
    document_id: str,
    regenerate: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Download the generated PDF analysis report for a document."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    if doc.processing_status != "analyzed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{document_id}' has not been analyzed yet.",
        )

    report_row = (
        db.query(AnalysisReport)
        .filter(AnalysisReport.document_id == document_id)
        .order_by(AnalysisReport.created_at.desc())
        .first()
    )
    default_report_path = settings.reports_dir / f"LegalEase_Report_{document_id}.pdf"
    candidate_path = Path(report_row.report_path) if report_row else default_report_path
    try:
        report_path = resolve_contained_path(settings.reports_dir, candidate_path)
    except DocumentValidationError:
        report_path = resolve_contained_path(settings.reports_dir, default_report_path)

    file_needs_generation = not report_path.exists() or report_path.stat().st_size == 0

    if file_needs_generation and not regenerate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report file missing or corrupted. Re-run analysis to regenerate.",
        )

    if file_needs_generation:
        # Regenerate cleanly inside managed reports directory from SQLite state
        clauses = (
            db.query(Clause)
            .filter(Clause.document_id == document_id)
            .order_by(Clause.clause_id.asc())
            .all()
        )
        risks = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.document_id == document_id)
            .order_by(RiskAssessment.risk_score.desc())
            .all()
        )
        comparisons = (
            db.query(Comparison)
            .filter(Comparison.document_id == document_id)
            .order_by(Comparison.clause_id.asc())
            .all()
        )
        counts = {"no_notable_risk": 0, "uncertain": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
        scored_count = 0
        for r in risks:
            counts[r.risk_level] = counts.get(r.risk_level, 0) + 1
            if r.risk_score is not None:
                scored_count += 1
        overall_score = doc.overall_risk_score or 0.0
        overview = {
            "overall_risk_score": overall_score,
            "overall_risk_level": doc.overall_risk_level or (
                "no_notable_risk" if scored_count == 0 else classify_risk_level(overall_score)
            ),
            "total_clauses": len(clauses),
            "scored_clauses_count": scored_count,
            "no_notable_risk_count": counts["no_notable_risk"],
            "uncertain_count": counts["uncertain"],
            "low_count": counts["low"],
            "medium_count": counts["medium"],
            "high_count": counts["high"],
            "critical_count": counts["critical"],
        }

        missing_clauses = {}
        if doc.missing_clauses_json:
            try:
                missing_clauses = json.loads(doc.missing_clauses_json)
            except Exception:
                missing_clauses = {}

        formatted_comparisons = []
        for comp in comparisons:
            diffs = []
            if comp.differences:
                try:
                    loaded_diff = json.loads(comp.differences)
                    if isinstance(loaded_diff, list):
                        diffs = loaded_diff
                    elif loaded_diff:
                        diffs = [str(loaded_diff)]
                except Exception:
                    diffs = [str(comp.differences)]
            formatted_comparisons.append(
                {
                    "clause_id": comp.clause_id,
                    "reference_source": comp.reference_source,
                    "jurisdiction": "Illustrative Reference",
                    "differences": diffs,
                    "recommendation": comp.recommendation or "",
                }
            )

        try:
            generate_analysis_pdf(
                output_path=report_path,
                document_meta={
                    "document_id": doc.document_id,
                    "filename": doc.filename,
                    "file_type": doc.file_type,
                    "page_count": doc.page_count,
                    "detected_contract_type": doc.detected_contract_type,
                    "analysis_mode": doc.analysis_mode or "deterministic_fallback",
                    "gemini_status": doc.gemini_status,
                    "fallback_reason": doc.fallback_reason,
                    "embedding_backend": doc.embedding_backend,
                },
                overview=overview,
                executive_summary=doc.executive_summary or "",
                clauses=[
                    {
                        "clause_id": c.clause_id,
                        "page_number": c.page_number,
                        "end_page_number": c.end_page_number,
                        "location_type": c.location_type,
                        "paragraph_index": c.paragraph_index,
                        "section_title": c.section_title,
                        "category": c.category,
                        "title": c.title,
                        "description": c.description,
                        "original_text": c.original_text,
                    }
                    for c in clauses
                ],
                risk_results=[
                    {
                        "clause_id": r.clause_id,
                        "risk_level": r.risk_level,
                        "risk_score": r.risk_score,
                        "risk_title": r.risk_title,
                        "explanation": r.explanation,
                        "potential_impact": r.potential_impact,
                        "suggested_action": r.suggested_action,
                        "page_number": r.page_number,
                        "location_type": r.location_type,
                        "paragraph_index": r.paragraph_index,
                        "section_title": r.section_title,
                        "finding_type": r.finding_type,
                        "verified": r.verified,
                    }
                    for r in risks
                ],
                comparisons=formatted_comparisons,
                missing_clauses=missing_clauses,
            )
            if report_row is None:
                db.add(AnalysisReport(document_id=document_id, report_path=str(report_path)))
                db.commit()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report file missing or corrupted. Re-run analysis to regenerate. Error: {exc}",
            )

    if not report_path.exists() or report_path.stat().st_size == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report file missing or corrupted. Re-run analysis to regenerate.",
        )

    safe_download_name = f"LegalEase_Report_{document_id}.pdf"
    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=safe_download_name,
    )

