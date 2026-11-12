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
from backend.services.pdf_service import generate_analysis_pdf
from backend.services.scoring_service import classify_risk_level


router = APIRouter(prefix="/api", tags=["Reports"])


@router.get("/reports")
def list_reports(db: Session = Depends(get_db)):
    """List generated analysis reports ordered newest first."""
    reports = (
        db.query(AnalysisReport, Document)
        .join(Document, AnalysisReport.document_id == Document.document_id)
        .order_by(AnalysisReport.created_at.desc())
        .all()
    )
    return [
        {
            "document_id": doc.document_id,
            "filename": doc.filename,
            "detected_contract_type": doc.detected_contract_type,
            "overall_risk_score": doc.overall_risk_score,
            "overall_risk_level": doc.overall_risk_level,
            "report_exists": Path(rep.report_path).exists(),
            "created_at": rep.created_at,
        }
        for rep, doc in reports
    ]


@router.get("/report/{document_id}")
def download_report(
    document_id: str,
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
    report_path = (
        Path(report_row.report_path)
        if report_row
        else settings.reports_dir / f"LegalEase_Report_{document_id}.pdf"
    )

    if not report_path.exists():
        # Regenerate cleanly from SQLite state if file was cleaned up
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
        counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for r in risks:
            counts[r.risk_level] = counts.get(r.risk_level, 0) + 1
        overall_score = doc.overall_risk_score or 0.0
        overview = {
            "overall_risk_score": overall_score,
            "overall_risk_level": doc.overall_risk_level or classify_risk_level(overall_score),
            "total_clauses": len(clauses),
            "low_count": counts["low"],
            "medium_count": counts["medium"],
            "high_count": counts["high"],
            "critical_count": counts["critical"],
        }
        missing_clauses = (
            json.loads(doc.missing_clauses_json) if doc.missing_clauses_json else {}
        )
        generate_analysis_pdf(
            output_path=report_path,
            document_meta={
                "document_id": doc.document_id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "page_count": doc.page_count,
                "detected_contract_type": doc.detected_contract_type,
                "analysis_mode": doc.analysis_mode or "deterministic_fallback",
            },
            overview=overview,
            executive_summary=doc.executive_summary or "",
            clauses=[
                {
                    "clause_id": c.clause_id,
                    "page_number": c.page_number,
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
                    "verified": r.verified,
                }
                for r in risks
            ],
            comparisons=[
                {
                    "clause_id": comp.clause_id,
                    "reference_source": comp.reference_source,
                    "jurisdiction": "Illustrative Reference",
                    "differences": json.loads(comp.differences) if comp.differences else [],
                    "recommendation": comp.recommendation or "",
                }
                for comp in comparisons
            ],
            missing_clauses=missing_clauses,
        )
        if report_row is None:
            db.add(AnalysisReport(document_id=document_id, report_path=str(report_path)))
            db.commit()

    safe_download_name = f"LegalEase_Report_{document_id}.pdf"
    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=safe_download_name,
    )

