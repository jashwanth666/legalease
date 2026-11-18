"""Specialized LangGraph node functions coordinating LegalEase processing stages."""

import json
import logging
from pathlib import Path
from typing import Any

from backend.agents.classification_agent import ClassificationAgent
from backend.agents.comparison_agent import ComparisonAgent
from backend.agents.extraction_agent import ExtractionAgent
from backend.agents.metadata_agent import MetadataAgent
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
from backend.guardrails.document_guard import (
    DocumentValidationError,
    resolve_contained_path,
    safe_delete_file,
    validate_uploaded_document,
)
from backend.ingestion.clause_splitter import split_pages_into_clauses
from backend.ingestion.document_loader import ocr_pdf_pages
from backend.retrieval.embeddings import EmbeddingService
from backend.retrieval.retriever import TemplateRetriever
from backend.schemas.clause import ClauseClassification, ExtractedClause
from backend.schemas.risk import RiskFinding, RiskOverview
from backend.services.llm_service import LLMService
from backend.services.pdf_service import generate_analysis_pdf
from backend.services.scoring_service import calculate_overall_risk_overview


logger = logging.getLogger(__name__)

STAGE_PROGRESS: dict[str, int] = {
    "document_validation": 8,
    "text_extraction": 16,
    "ocr": 24,
    "clause_splitting": 32,
    "clause_classification": 40,
    "risk_assessment": 50,
    "template_comparison": 60,
    "missing_clause_detection": 68,
    "metadata_extraction": 76,
    "evidence_verification": 84,
    "summary_generation": 92,
    "pdf_generation": 100,
}

ALL_WORKFLOW_STAGES: list[str] = list(STAGE_PROGRESS.keys())


def record_stage_progress(document_id: str, stage_name: str) -> None:
    """Idempotently persist real-time workflow stage progress into SQLite."""
    if not document_id:
        return
    session = db_module.SessionLocal()
    try:
        doc = session.query(Document).filter(Document.document_id == document_id).first()
        if doc is not None:
            doc.current_stage = stage_name
            target_pct = STAGE_PROGRESS.get(stage_name, doc.progress_percent or 0)
            if target_pct > (doc.progress_percent or 0):
                doc.progress_percent = target_pct

            try:
                completed = json.loads(doc.completed_stages_json or "[]")
            except Exception:
                completed = []
            if stage_name not in completed:
                completed.append(stage_name)
            doc.completed_stages_json = json.dumps(completed)
            if doc.processing_status in ("queued", "uploaded"):
                doc.processing_status = "processing"
            session.commit()
    except Exception as exc:
        logger.warning("Could not record stage progress for %s (%s): %s", document_id, stage_name, exc)
    finally:
        session.close()


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
    record_stage_progress(state.get("document_id", ""), "document_validation")
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
    """Extract or load structured location-referenced text for the contract."""
    record_stage_progress(state.get("document_id", ""), "text_extraction")
    cfg = _resolve_runtime_paths(state)
    document_id = state["document_id"]
    agent = ExtractionAgent()

    try:
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
    except Exception as exc:
        logger.exception("Text extraction failed for document_id=%s", document_id)
        return {"processing_errors": [f"Text extraction failed ({type(exc).__name__}): {exc}"]}

    ocr_required = bool(extracted.get("ocr_required", False))
    return {
        "pages": extracted.get("pages", []),
        "extracted_text": extracted.get("full_text", ""),
        "ocr_required": ocr_required,
        "processing_errors": [],
    }


def ocr_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run OCR on a scanned PDF and update pages/extracted_text in state."""
    record_stage_progress(state.get("document_id", ""), "ocr")
    file_path = Path(state.get("file_path", ""))
    if not file_path.exists():
        return {
            "ocr_attempted": True,
            "ocr_succeeded": False,
            "ocr_error": f"File not found for OCR: {file_path}",
            "processing_errors": [f"OCR skipped: file not found ({file_path})."],
        }

    try:
        result = ocr_pdf_pages(file_path)
    except Exception as exc:
        logger.exception("ocr_pdf_pages raised unexpectedly for %s", state.get("document_id"))
        err = f"Unexpected OCR error ({type(exc).__name__}): {exc}"
        return {
            "ocr_attempted": True,
            "ocr_succeeded": False,
            "ocr_error": err,
            "processing_errors": [err],
        }

    updates: dict[str, Any] = {
        "ocr_attempted": result.ocr_attempted,
        "ocr_succeeded": result.ocr_succeeded,
        "ocr_error": result.ocr_error,
    }

    if result.ocr_succeeded and result.pages:
        full_text = "\n\n".join(
            f"[Page {p['page_number']}]\n{p['text']}"
            for p in result.pages
            if p.get("text")
        ).strip()
        updates["pages"] = result.pages
        updates["extracted_text"] = full_text
        # Clear the ocr_required flag so downstream nodes proceed normally
        updates["ocr_required"] = False
    else:
        # OCR failed — surface the error so the workflow can terminate cleanly
        err_msg = result.ocr_error or "OCR failed with no additional details."
        updates["processing_errors"] = [err_msg]

    return updates


def split_into_clauses_node(state: dict[str, Any]) -> dict[str, Any]:
    """Segment extracted pages/paragraphs into complete legal clauses preserving locations."""
    record_stage_progress(state.get("document_id", ""), "clause_splitting")
    try:
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
    except Exception as exc:
        logger.exception("Clause splitting failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Clause segmentation failed ({type(exc).__name__}): {exc}"]}


async def classify_clauses_node(state: dict[str, Any]) -> dict[str, Any]:
    """Classify each extracted clause using Gemini or explicit deterministic fallback."""
    record_stage_progress(state.get("document_id", ""), "clause_classification")
    try:
        cfg = _resolve_runtime_paths(state)
        clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
        llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
        agent = ClassificationAgent(llm_service=llm)

        classifications, mode = await agent.aclassify_clauses(clauses)
        telemetry = {**agent.last_run_meta, "stage": "classification", "mode": mode}
        return {
            "classified_clauses": [c.model_dump() for c in classifications],
            "analysis_mode": mode,
            "llm_telemetry": [telemetry],
        }
    except Exception as exc:
        logger.exception("Classification node failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Clause classification failed ({type(exc).__name__}): {exc}"]}


async def risk_assessment_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assess clause risks using Gemini/fallback reasoning and Python risk scoring."""
    record_stage_progress(state.get("document_id", ""), "risk_assessment")
    try:
        cfg = _resolve_runtime_paths(state)
        clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
        classified = [
            ClauseClassification.model_validate(c) for c in state.get("classified_clauses", [])
        ]
        llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
        agent = RiskAgent(llm_service=llm)

        findings, mode = await agent.aassess_clauses(clauses, classified)
        telemetry = {**agent.last_run_meta, "stage": "risk_assessment", "mode": mode}
        return {
            "risk_results": [f.model_dump() for f in findings],
            "llm_telemetry": [telemetry],
        }
    except Exception as exc:
        logger.exception("Risk assessment node failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Risk assessment failed ({type(exc).__name__}): {exc}"]}


async def rag_template_comparison_node(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve relevant illustrative reference clauses via FAISS and compare clauses."""
    record_stage_progress(state.get("document_id", ""), "template_comparison")
    try:
        cfg = _resolve_runtime_paths(state)
        clauses = [ExtractedClause.model_validate(c) for c in state.get("clauses", [])]
        classified = [
            ClauseClassification.model_validate(c) for c in state.get("classified_clauses", [])
        ]
        llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
        embedding_service = EmbeddingService(allow_download=False)
        retriever = TemplateRetriever(
            vectorstore_dir=cfg["vectorstore_dir"],
            templates_dir=cfg["templates_dir"],
            embedding_service=embedding_service,
        )
        agent = ComparisonAgent(retriever=retriever, llm_service=llm)

        comparisons, retrieved_map, mode = await agent.acompare_clauses(
            clauses=clauses,
            classifications=classified,
            contract_type=state.get("contract_type"),
        )
        telemetry = {
            **agent.last_run_meta,
            "stage": "rag_comparison",
            "mode": mode,
            "embedding_backend": embedding_service.backend_name,
        }
        return {
            "retrieved_references": retrieved_map,
            "comparison_results": [c.model_dump() for c in comparisons],
            "embedding_backend": embedding_service.backend_name,
            "llm_telemetry": [telemetry],
        }
    except Exception as exc:
        logger.exception("RAG template comparison node failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"RAG comparison failed ({type(exc).__name__}): {exc}"]}


def missing_clause_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """Compare classified clause categories against the contract-type checklist."""
    record_stage_progress(state.get("document_id", ""), "missing_clause_detection")
    try:
        contract_type = state.get("contract_type") or "General Commercial Agreement"
        classified_clauses = state.get("classified_clauses", [])
        missing = SummaryAgent.detect_missing_clauses(contract_type, classified_clauses)
        return {"missing_clauses": missing}
    except Exception as exc:
        logger.exception("Missing clause detection failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Missing clause detection failed ({type(exc).__name__}): {exc}"]}


async def extract_metadata_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract structured 16-field contract metadata with grounded evidence."""
    record_stage_progress(state.get("document_id", ""), "metadata_extraction")
    try:
        cfg = _resolve_runtime_paths(state)
        llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
        agent = MetadataAgent(llm_service=llm)
        metadata = await agent.aextract_metadata(
            full_text=state.get("extracted_text", ""),
            clauses=state.get("clauses", []),
            document_id=state.get("document_id", ""),
            filename=state.get("filename", ""),
        )
        telemetry = {
            **agent.last_run_meta,
            "stage": "metadata_extraction",
        }
        return {
            "contract_metadata": metadata.to_dict(),
            "llm_telemetry": [telemetry],
        }
    except Exception as exc:
        logger.exception("Metadata extraction failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Metadata extraction failed ({type(exc).__name__}): {exc}"]}


def merge_results_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synchronize parallel branch outputs and summarize Gemini fallback/telemetry state."""
    sources = set()
    for c in state.get("classified_clauses", []):
        sources.add(c.get("classification_source", "deterministic_fallback"))
    for r in state.get("risk_results", []):
        sources.add(r.get("analysis_source", "deterministic_fallback"))
    for comp in state.get("comparison_results", []):
        sources.add(comp.get("analysis_source", "deterministic_fallback"))
    meta = state.get("contract_metadata") or {}
    if meta.get("extraction_source"):
        sources.add(meta["extraction_source"])

    if sources == {"gemini"}:
        mode = "gemini"
    elif "gemini" in sources:
        mode = "hybrid_fallback"
    else:
        mode = "deterministic_fallback"

    telemetry = state.get("llm_telemetry") or []
    fallback_used = mode != "gemini" or any(bool(t.get("fallback_used")) for t in telemetry)
    reasons = [str(t["fallback_reason"]) for t in telemetry if t.get("fallback_reason")]
    statuses = [str(t["gemini_status"]) for t in telemetry if t.get("gemini_status")]

    # Prefer surfacing specific non-"ok" status (e.g., rate_limited, invalid_credentials, missing_key)
    non_ok = [s for s in statuses if s != "ok"]
    gemini_status = non_ok[-1] if non_ok else ("ok" if not fallback_used else "unknown_error")
    fallback_reason = "; ".join(dict.fromkeys(reasons)) if reasons else None

    return {
        "analysis_mode": mode,
        "gemini_status": gemini_status,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
    }


def verify_evidence_node(state: dict[str, Any]) -> dict[str, Any]:
    """Verify every risk finding, comparison, missing clause, and metadata item against source evidence."""
    record_stage_progress(state.get("document_id", ""), "evidence_verification")
    try:
        risk_results = list(state.get("risk_results", []))
        comparison_results = list(state.get("comparison_results", []))
        missing_clauses = dict(state.get("missing_clauses", {}))
        contract_metadata = dict(state.get("contract_metadata", {}))

        verification = SummaryAgent.verify_evidence(
            pages=state.get("pages", []),
            clauses=state.get("clauses", []),
            classified_clauses=state.get("classified_clauses", []),
            risk_results=risk_results,
            retrieved_references=state.get("retrieved_references", {}),
            comparison_results=comparison_results,
            missing_clauses=missing_clauses,
            contract_metadata=contract_metadata,
            extracted_text=state.get("extracted_text", ""),
        )
        return {
            "risk_results": risk_results,
            "comparison_results": comparison_results,
            "missing_clauses": missing_clauses,
            "contract_metadata": contract_metadata,
            "verified_findings": verification,
        }
    except Exception as exc:
        logger.exception("Evidence verification failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Evidence verification failed ({type(exc).__name__}): {exc}"]}


async def generate_summary_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a plain-English executive summary from verified findings."""
    record_stage_progress(state.get("document_id", ""), "summary_generation")
    try:
        cfg = _resolve_runtime_paths(state)
        risk_models = [RiskFinding.model_validate(r) for r in state.get("risk_results", [])]
        overview = calculate_overall_risk_overview(risk_models)

        llm = LLMService(api_key=cfg["api_key"], model_name=cfg["model_name"])
        agent = SummaryAgent(llm_service=llm)
        summary_text, summary_mode = await agent.agenerate_summary(
            filename=state.get("filename", ""),
            contract_type=state.get("contract_type", "General Commercial Agreement"),
            overview=overview,
            risk_results=state.get("risk_results", []),
            comparison_results=state.get("comparison_results", []),
            missing_clauses=state.get("missing_clauses", {}),
            fallback_reason=state.get("fallback_reason"),
        )

        updates: dict[str, Any] = {"final_summary": summary_text}
        if summary_mode != "gemini":
            meta = agent.last_run_meta
            if state.get("analysis_mode") == "gemini":
                updates["analysis_mode"] = "hybrid_fallback"
            updates["fallback_used"] = True
            if meta.get("gemini_status") and meta["gemini_status"] != "ok":
                updates["gemini_status"] = state.get("gemini_status") if state.get("gemini_status") not in (None, "ok") else meta["gemini_status"]
            if meta.get("fallback_reason") and not state.get("fallback_reason"):
                updates["fallback_reason"] = meta["fallback_reason"]
        return updates
    except Exception as exc:
        logger.exception("Summary generation failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Executive summary generation failed ({type(exc).__name__}): {exc}"]}


def calculate_overview_node(state: dict[str, Any]) -> dict[str, Any]:
    """Compute final illustrative overall risk score and distribution overview."""
    try:
        risk_models = [RiskFinding.model_validate(r) for r in state.get("risk_results", [])]
        overview: RiskOverview = calculate_overall_risk_overview(risk_models)
        return {
            "overall_risk_score": overview.overall_risk_score,
            "overall_risk_level": overview.overall_risk_level,
            "risk_overview": overview.model_dump(),
        }
    except Exception as exc:
        logger.exception("Overview scoring failed for document_id=%s", state.get("document_id"))
        return {"processing_errors": [f"Risk overview calculation failed ({type(exc).__name__}): {exc}"]}


def save_results_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist clauses, risk assessments, comparisons, and summary to SQLite before PDF generation."""
    if state.get("processing_errors"):
        return {"db_saved": False}

    cfg = _resolve_runtime_paths(state)
    document_id = state["document_id"]
    class_map = {c["clause_id"]: c for c in state.get("classified_clauses", [])}

    db = db_module.SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == document_id).first()
        if doc is None:
            return {"db_saved": False, "processing_errors": [f"Database record missing for {document_id}."]}

        # Clear prior analysis and stale reports for idempotent re-analysis
        prior_reports = db.query(AnalysisReport).filter(AnalysisReport.document_id == document_id).all()
        for rep in prior_reports:
            try:
                safe_delete_file(cfg["reports_dir"], Path(rep.report_path))
            except DocumentValidationError:
                pass
        db.query(AnalysisReport).filter(AnalysisReport.document_id == document_id).delete()
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
                    page_number=cl.get("page_number"),
                    end_page_number=cl.get("end_page_number"),
                    location_type=cl.get("location_type", "pdf_page"),
                    paragraph_index=cl.get("paragraph_index"),
                    section_title=cl.get("section_title"),
                    segmentation_confidence=cl.get("segmentation_confidence", "high"),
                    segmentation_uncertain=bool(cl.get("segmentation_uncertain", False)),
                )
            )

        for rf in state.get("risk_results", []):
            db.add(
                RiskAssessment(
                    document_id=document_id,
                    clause_id=rf["clause_id"],
                    risk_level=rf["risk_level"],
                    risk_score=float(rf["risk_score"]) if rf.get("risk_score") is not None else None,
                    risk_title=rf.get("risk_title"),
                    explanation=rf["explanation"],
                    potential_impact=rf.get("potential_impact"),
                    suggested_action=rf.get("suggested_action"),
                    page_number=rf.get("page_number"),
                    location_type=rf.get("location_type", "pdf_page"),
                    paragraph_index=rf.get("paragraph_index"),
                    section_title=rf.get("section_title"),
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
                    insufficient_evidence=bool(comp.get("insufficient_evidence", False)),
                    verified=bool(comp.get("verified", True)),
                )
            )

        # Mark as 'partially_analyzed' until PDF generation also succeeds
        doc.processing_status = "partially_analyzed"
        if state.get("ocr_succeeded"):
            doc.ocr_required = False
        doc.detected_contract_type = state.get("contract_type")
        doc.overall_risk_score = state.get("overall_risk_score")
        doc.overall_risk_level = state.get("overall_risk_level")
        doc.executive_summary = state.get("final_summary")
        doc.missing_clauses_json = json.dumps(
            state.get("missing_clauses", {}), ensure_ascii=False
        )
        doc.metadata_json = json.dumps(
            state.get("contract_metadata", {}), ensure_ascii=False
        )
        doc.analysis_mode = state.get("analysis_mode", "deterministic_fallback")
        doc.gemini_status = state.get("gemini_status", "missing_key")
        doc.fallback_used = bool(state.get("fallback_used", False))
        doc.fallback_reason = state.get("fallback_reason")
        doc.embedding_backend = state.get("embedding_backend", "deterministic_hash")
        doc.last_error = None
        db.commit()
        return {"db_saved": True}
    except Exception as exc:
        db.rollback()
        logger.exception("Failed saving analysis results for document_id=%s", document_id)
        return {"db_saved": False, "processing_errors": [f"Database save error: {exc}"]}
    finally:
        db.close()


def generate_pdf_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate downloadable ReportLab PDF report and finalize document status as 'analyzed'."""
    if state.get("processing_errors") or not state.get("db_saved"):
        return {"pdf_generated": False}

    cfg = _resolve_runtime_paths(state)
    document_id = state["document_id"]
    record_stage_progress(document_id, "pdf_generation")
    try:
        report_path = resolve_contained_path(
            cfg["reports_dir"], cfg["reports_dir"] / f"LegalEase_Report_{document_id}.pdf"
        )
    except DocumentValidationError as exc:
        return {"pdf_generated": False, "processing_errors": [exc.message]}

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

    is_docx = state.get("file_type") == "docx"
    doc_meta = {
        "document_id": document_id,
        "filename": state.get("filename", ""),
        "file_type": state.get("file_type", ""),
        "page_count": 0 if is_docx else len(state.get("pages", [])),
        "detected_contract_type": state.get("contract_type"),
        "analysis_mode": state.get("analysis_mode", "deterministic_fallback"),
        "gemini_status": state.get("gemini_status"),
        "fallback_reason": state.get("fallback_reason"),
        "embedding_backend": state.get("embedding_backend"),
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
            verification_summary=state.get("verified_findings", {}),
        )
    except Exception as exc:
        logger.exception("PDF report generation failed for document_id=%s", document_id)
        return {"pdf_generated": False, "processing_errors": [f"PDF generation error: {exc}"]}

    db = db_module.SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == document_id).first()
        if doc is None:
            return {"pdf_generated": False, "processing_errors": [f"Document disappeared for {document_id}."]}
        db.query(AnalysisReport).filter(AnalysisReport.document_id == document_id).delete()
        db.add(AnalysisReport(document_id=document_id, report_path=str(report_path)))
        doc.processing_status = "analyzed"
        doc.current_stage = "completed"
        doc.progress_percent = 100
        doc.last_error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed saving report record for document_id=%s", document_id)
        return {"pdf_generated": False, "processing_errors": [f"Report DB save error: {exc}"]}
    finally:
        db.close()

    return {"report_path": str(report_path), "pdf_generated": True}
