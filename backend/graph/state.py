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
    extracted_text: str
    pages: list[dict[str, Any]]
    clauses: list[dict[str, Any]]
    classified_clauses: list[dict[str, Any]]
    risk_results: list[dict[str, Any]]
    retrieved_references: dict[str, list[dict[str, Any]]]
    comparison_results: list[dict[str, Any]]
    missing_clauses: dict[str, Any]
    verified_findings: dict[str, Any]
    final_summary: str
    overall_risk_score: float
    overall_risk_level: str
    risk_overview: dict[str, Any]
    analysis_mode: str
    report_path: str
    processing_errors: Annotated[list[str], operator.add]
    runtime_config: dict[str, Any]

