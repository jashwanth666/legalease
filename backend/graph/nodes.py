"""Specialized LangGraph node functions coordinating LegalEase processing stages."""

import json
import logging
from pathlib import Path
from typing import Any

from backend.agents.classification_agent import ClassificationAgent
from backend.agents.comparison_agent import ComparisonAgent
from backend.agents.extraction_agent import ExtractionAgent
from backend.agents.risk_agent import RiskAgent
from backend.agents.summary_agent import SummaryAgent, detect_contract_type
from backend.config import get_settings
from backend.database import (
    AnalysisReport,
    Clause,
    Comparison,
    Document,
    RiskAssessment,
    db as db_module,
)
from backend.guardrails.document_guard import DocumentValidationError, validate_uploaded_document
from backend.ingestion.clause_splitter import split_pages_into_clauses
from backend.retrieval.embeddings import EmbeddingService
from backend.retrieval.retriever import TemplateRetriever
from backend.schemas.clause import ClauseClassification, ExtractedClause
from backend.schemas.risk import RiskFinding, RiskOverview
from backend.services.llm_service import LLMService
from backend.services.pdf_service import generate_analysis_pdf
from backend.services.scoring_service import calculate_overall_risk_overview


logger = logging.getLogger(__name__)


def _resolve_runtime_paths(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    cfg = state.get("runtime_config") or {}
    return {
        "api_key": cfg.get("gemini_api_key", settings.gemini_api_key),
        "model_name": cfg.get("gemini_model", settings.gemini_model),
        "extracted_dir": Path(cfg.get("extracted_dir", settings.extracted_dir)),
        "vectorstore_dir": Path(cfg.get("vectorstore_dir", settings.vectorstore_dir)),
        "templates_dir": Path(cfg.get("templates_dir", settings.reference_templates_dir)),
        "reports_dir": Path(cfg.get("reports_dir", settings.reports_dir)),
        "max_size_bytes": settings.max_upload_size_bytes,
    }


def validate_document_node(state: dict[str, Any]) -> dict[str, Any]:
    """Validate document presence and binary integrity before extraction."""
    cfg = _resolve_runtime_paths(state)
    file_path = Path(state["file_path"])
    filename = state["filename"]

    if not file_path.exists():
        return {"processing_errors": [f"Uploaded file not found for {state['document_id']}."]}

    try:
        raw = file_path.read_bytes()
        validated = validate_uploaded_document(
            filename=filename,
            content=raw,
            max_size_bytes=cfg["max_size_bytes"],
        )
        return {"file_type": validated.file_type}
    except DocumentValidationError as exc:
        return {"processing_errors": [exc.message]}
    except Exception as exc:
        logger.exception("Validation failed for %s", state.get("document_id"))
        return {"processing_errors": [f"Validation error: {exc}"]}


def extract_document_text_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract or load structured page-referenced text for the contract."""
    cfg = _resolve_runtime_paths(state)
    document_id = state["document_id"]
    agent = ExtractionAgent()

    existing = agent.get_extracted(document_id, cfg["extracted_dir"])
    if existing and existing.get("pages"):
        extracted = existing
    else:
        extracted = agent.run(
            file_path=Path(state["file_path"]),
            document_id=document_id,
            filename=state["filename"],
            file_type=state["file_type"],
            extracted_dir=cfg["extracted_dir"],
        )

    ocr_required = bool(extracted.get("ocr_required", False))
    errors: list[str] = []
    if ocr_required:
        errors.append(
            extracted.get("warning")
            or "No usable text detected; OCR is required before analysis."
        )

    return {
        "pages": extracted.get("pages", []),
        "extracted_text": extracted.get("full_text", ""),
        "ocr_required": ocr_required,
        "processing_errors": errors,
    }


def split_into_clauses_node(state: dict[str, Any]) -> dict[str, Any]:
    """Segment extracted pages into complete legal clauses preserving page references."""
    pages = state.get("pages", [])
    clauses = split_pages_into_clauses(pages)
    if not clauses:
        return {
            "clauses": [],
            "processing_errors": ["No identifiable clauses could be segmented from extracted text."],
        }

    contract_type = detect_contract_type(
        filename=state.get("filename", ""),
        full_text=state.get("extracted_text", ""),
    )
    return {
        "clauses": [c.model_dump() for c in clauses],
        "contract_type": contract_type,
    }


def classify_clauses_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify each extracted clause using Gemini or explicit deterministic fallback."""
    cfg = _resolve_runtime_paths(state)
    clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
    llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
    agent = ClassificationAgent(llm_service=llm)

    classifications, mode = agent.classify_clauses(clauses)
    return {
        "classified_clauses": [c.model_dump() for c in classifications],
        "analysis_mode": mode,
    }


def risk_assessment_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assess clause risks using Gemini/fallback reasoning and Python risk scoring."""
    cfg = _resolve_runtime_paths(state)
    clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
    classified = [
        ClauseClassification.model_validate(c) for c in state.get("classified_clauses", [])
    ]
    llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
    agent = RiskAgent(llm_service=llm)

    findings, _ = agent.assess_clauses(clauses, classified)
    return {"risk_results": [f.model_dump() for f in findings]}


def rag_template_comparison_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant illustrative reference clauses via FAISS and compare clauses."""
    cfg = _resolve_runtime_paths(state)
    clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
    classified = [
        ClauseClassification.model_validate(c) for c in state.get("classified_clauses", [])
    ]
    llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
    retriever = TemplateRetriever(
        vectorstore_dir=cfg["vectorstore_dir"],
        templates_dir=cfg["templates_dir"],
        embedding_service=EmbeddingService(allow_download=False),
    )
    agent = ComparisonAgent(retriever=retriever, llm_service=llm)

    comparisons, retrieved_map, _ = agent.compare_clauses(
        clauses=clauses,
        classifications=classified,
        contract_type=state.get("contract_type"),
    )
    return {
        "retrieved_references": retrieved_map,
        "comparison_results": [c.model_dump() for c in comparisons],
    }


def missing_clause_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """Compare classified clause categories against the contract-type checklist."""
    contract_type = state.get("contract_type") or "General Commercial Agreement"
    classified_clauses = state.get("classified_clauses", [])
    missing = SummaryAgent.detect_missing_clauses(contract_type, classified_clauses)
    return {"missing_clauses": missing}


def merge_results_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synchronize parallel branch outputs (risk, RAG comparison, missing clauses)."""
    sources = set()
    for c in state.get("classified_clauses", []):
        sources.add(c.get("classification_source", "deterministic_fallback"))
    for r in state.get("risk_results", []):
        sources.add(r.get("analysis_source", "deterministic_fallback"))
    for comp in state.get("comparison_results", []):
        sources.add(comp.get("analysis_source", "deterministic_fallback"))

    if sources == {"gemini"}:
        mode = "gemini"
    elif "gemini" in sources:
        mode = "hybrid_fallback"
    else:
        mode = "deterministic_fallback"

    return {"analysis_mode": mode}


def verify_evidence_node(state: dict[str, Any]) -> dict[str, Any]:
    """Verify every risk finding, comparison, and missing clause against source evidence."""
    risk_results = list(state.get("risk_results", []))
    comparison_results = list(state.get("comparison_results", []))
    missing_clauses = dict(state.get("missing_clauses", {}))

    verification = SummaryAgent.verify_evidence(
        pages=state.get("pages", []),
        clauses=state.get("clauses", []),
        classified_clauses=state.get("classified_clauses", []),
        risk_results=risk_results,
        retrieved_references=state.get("retrieved_references", {}),
        comparison_results=comparison_results,
        missing_clauses=missing_clauses,
    )
    return {
        "risk_results": risk_results,
        "comparison_results": comparison_results,
        "missing_clauses": missing_clauses,
        "verified_findings": verification,
    }


def generate_summary_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a plain-English executive summary from verified findings."""
    cfg = _resolve_runtime_paths(state)
    risk_models = [RiskFinding.model_validate(r) for r in state.get("risk_results", [])]
    overview = calculate_overall_risk_overview(risk_models)

    llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
    agent = SummaryAgent(llm_service=llm)
    summary_text, _ = agent.generate_summary(
        filename=state.get("filename", ""),
        contract_type=state.get("contract_type", "General Commercial Agreement"),
        overview=overview,
        risk_results=state.get("risk_results", []),
        comparison_results=state.get("comparison_results", []),
        missing_clauses=state.get("missing_clauses", {}),
    )
    return {"final_summary": summary_text}


def calculate_overview_node(state: dict[str, Any]) -> dict[str, Any]:
    """Compute final illustrative overall risk score and distribution overview."""
    risk_models = [RiskFinding.model_validate(r) for r in state.get("risk_results", [])]
    overview: RiskOverview = calculate_overall_risk_overview(risk_models)
    return {
        "overall_risk_score": overview.overall_risk_score,
        "overall_risk_level": overview.overall_risk_level,
        "risk_overview": overview.model_dump(),
    }


def save_results_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist clauses, risk assessments, comparisons, and document summary to SQLite."""
    document_id = state["document_id"]
    class_map = {
        c["clause_id"]: c for c in state.get("classified_clauses", [])
    }

    db = db_module.SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == document_id).first()
        if doc is None:
            return {"processing_errors": [f"Database record missing for {document_id}."]}

        # Clear prior analysis rows for idempotent re-analysis
        db.query(Clause).filter(Clause.document_id == document_id).delete()
        db.query(RiskAssessment).filter(RiskAssessment.document_id == document_id).delete()
        db.query(Comparison).filter(Comparison.document_id == document_id).delete()

        for cl in state.get("clauses", []):
            cid = cl["clause_id"]
            cls = class_map.get(cid, {})
            db.add(
                Clause(
                    document_id=document_id,
                    clause_id=cid,
                    title=cl["title"],
                    category=cls.get("category", cl["category"]),
                    description=cls.get("description"),
                    confidence=cls.get("confidence"),
                    classification_source=cls.get("classification_source", "deterministic_fallback"),
                    original_text=cl["original_text"],
                    page_number=int(cl.get("page_number", 1)),
                )
            )

        for rf in state.get("risk_results", []):
            db.add(
                RiskAssessment(
                    document_id=document_id,
                    clause_id=rf["clause_id"],
                    risk_level=rf["risk_level"],
                    risk_score=float(rf["risk_score"]),
                    risk_title=rf.get("risk_title"),
                    explanation=rf["explanation"],
                    potential_impact=rf.get("potential_impact"),
                    suggested_action=rf.get("suggested_action"),
                    page_number=int(rf.get("page_number", 1)),
                    verified=bool(rf.get("verified", True)),
                    finding_type=rf.get("finding_type", "detected_risk"),
                )
            )

        for comp in state.get("comparison_results", []):
            db.add(
                Comparison(
                    document_id=document_id,
                    clause_id=comp["clause_id"],
                    reference_text=comp["reference_clause"],
                    differences=json.dumps(comp.get("differences", []), ensure_ascii=False),
                    potential_implications=comp.get("potential_implications"),
                    recommendation=comp.get("recommendation"),
                    reference_source=comp["reference_source"],
                    similarity_score=comp.get("similarity_score"),
                    verified=bool(comp.get("verified", True)),
                )
            )

        doc.processing_status = "analyzed"
        doc.detected_contract_type = state.get("contract_type")
        doc.overall_risk_score = state.get("overall_risk_score")
        doc.overall_risk_level = state.get("overall_risk_level")
        doc.executive_summary = state.get("final_summary")
        doc.missing_clauses_json = json.dumps(
            state.get("missing_clauses", {}), ensure_ascii=False
        )
        doc.analysis_mode = state.get("analysis_mode", "deterministic_fallback")
        db.commit()
        return {}
    except Exception as exc:
        db.rollback()
        logger.exception("Failed saving analysis results for %s", document_id)
        return {"processing_errors": [f"Database save error: {exc}"]}
    finally:
        db.close()


def generate_pdf_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate downloadable ReportLab PDF report and register it in SQLite."""
    cfg = _resolve_runtime_paths(state)
    document_id = state["document_id"]
    report_path = cfg["reports_dir"] / f"LegalEase_Report_{document_id}.pdf"

    class_map = {c["clause_id"]: c for c in state.get("classified_clauses", [])}
    merged_clauses = []
    for cl in state.get("clauses", []):
        cls = class_map.get(cl["clause_id"], {})
        merged_clauses.append(
            {
                **cl,
                "category": cls.get("category", cl.get("category")),
                "description": cls.get("description"),
            }
        )

    doc_meta = {
        "document_id": document_id,
        "filename": state.get("filename", ""),
        "file_type": state.get("file_type", ""),
        "page_count": len(state.get("pages", [])),
        "detected_contract_type": state.get("contract_type"),
        "analysis_mode": state.get("analysis_mode", "deterministic_fallback"),
    }

    try:
        generate_analysis_pdf(
            output_path=report_path,
            document_meta=doc_meta,
            overview=state.get("risk_overview", {}),
            executive_summary=state.get("final_summary", ""),
            clauses=merged_clauses,
            risk_results=state.get("risk_results", []),
            comparisons=state.get("comparison_results", []),
            missing_clauses=state.get("missing_clauses", {}),
        )
    except Exception as exc:
        logger.exception("PDF report generation failed for %s", document_id)
        return {"processing_errors": [f"PDF generation error: {exc}"]}

    db = db_module.SessionLocal()
    try:
        db.query(AnalysisReport).filter(AnalysisReport.document_id == document_id).delete()
        db.add(AnalysisReport(document_id=document_id, report_path=str(report_path)))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed saving report record for %s", document_id)
        return {"processing_errors": [f"Report DB save error: {exc}"]}
    finally:
        db.close()

    return {"report_path": str(report_path)}
