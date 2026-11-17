"""Shared LangGraph workflow state definition for LegalEase."""

import operator
from typing import Annotated, Any, TypedDict


class LegalEaseState(TypedDict, total=False):
    """Shared TypedDict state passed across all LangGraph workflow nodes."""

    document_id: str
    filename: str
    file_path: str
    file_type: str
    contract_type: str
    ocr_required: bool
    ocr_attempted: bool
    ocr_succeeded: bool
    ocr_error: str | None
    extracted_text: str
    pages: list[dict[str, Any]]
    clauses: list[dict[str, Any]]
    classified_clauses: list[dict[str, Any]]
    risk_results: list[dict[str, Any]]
    retrieved_references: dict[str, list[dict[str, Any]]]
    comparison_results: list[dict[str, Any]]
    missing_clauses: dict[str, Any]
    contract_metadata: dict[str, Any]
    verified_findings: dict[str, Any]
    final_summary: str
    overall_risk_score: float
    overall_risk_level: str
    risk_overview: dict[str, Any]
    analysis_mode: str
    gemini_status: str
    fallback_used: bool
    fallback_reason: str | None
    embedding_backend: str
    llm_telemetry: Annotated[list[dict[str, Any]], operator.add]
    db_saved: bool
    pdf_generated: bool
    report_path: str
    processing_errors: Annotated[list[str], operator.add]
    runtime_config: dict[str, Any]

