"""LangGraph workflow orchestration for LegalEase contract intelligence."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.graph.nodes import (
    calculate_overview_node,
    classify_clauses_node,
    extract_document_text_node,
    generate_pdf_node,
    generate_summary_node,
    merge_results_node,
    missing_clause_detection_node,
    rag_template_comparison_node,
    risk_assessment_node,
    save_results_node,
    split_into_clauses_node,
    validate_document_node,
    verify_evidence_node,
)
from backend.graph.state import LegalEaseState


def _route_after_validation(state: LegalEaseState) -> str:
    if state.get("processing_errors"):
        return "stop"
    return "continue"


def _route_after_extraction(state: LegalEaseState) -> str:
    if state.get("ocr_required") or state.get("processing_errors") or not state.get("pages"):
        return "stop"
    return "continue"


def _route_after_splitting(state: LegalEaseState) -> str:
    if state.get("processing_errors") or not state.get("clauses"):
        return "stop"
    return "continue"


def _route_after_classification(state: LegalEaseState) -> list[str]:
    if state.get("processing_errors"):
        return [END]
    return ["risk_assessment", "rag_template_comparison", "missing_clause_detection"]


def _route_after_errors(state: LegalEaseState) -> str:
    if state.get("processing_errors"):
        return "stop"
    return "continue"


def _route_after_save(state: LegalEaseState) -> str:
    if state.get("processing_errors") or not state.get("db_saved"):
        return "stop"
    return "continue"


def build_legalease_workflow():
    """Compile the full LegalEase LangGraph StateGraph with parallel assessment branches."""
    graph = StateGraph(LegalEaseState)

    graph.add_node("validate_document", validate_document_node)
    graph.add_node("extract_document_text", extract_document_text_node)
    graph.add_node("split_into_clauses", split_into_clauses_node)
    graph.add_node("classify_clauses", classify_clauses_node)

    graph.add_node("risk_assessment", risk_assessment_node)
    graph.add_node("rag_template_comparison", rag_template_comparison_node)
    graph.add_node("missing_clause_detection", missing_clause_detection_node)

    graph.add_node("merge_results", merge_results_node)
    graph.add_node("verify_evidence", verify_evidence_node)
    graph.add_node("generate_summary", generate_summary_node)
    graph.add_node("calculate_overview", calculate_overview_node)
    graph.add_node("save_results", save_results_node)
    graph.add_node("generate_pdf", generate_pdf_node)

    graph.add_edge(START, "validate_document")
    graph.add_conditional_edges(
        "validate_document",
        _route_after_validation,
        {"continue": "extract_document_text", "stop": END},
    )
    graph.add_conditional_edges(
        "extract_document_text",
        _route_after_extraction,
        {"continue": "split_into_clauses", "stop": END},
    )
    graph.add_conditional_edges(
        "split_into_clauses",
        _route_after_splitting,
        {"continue": "classify_clauses", "stop": END},
    )

    # Conditional parallel fan-out from clause classification
    graph.add_conditional_edges("classify_clauses", _route_after_classification)

    # Fan-in to merge_results
    graph.add_edge("risk_assessment", "merge_results")
    graph.add_edge("rag_template_comparison", "merge_results")
    graph.add_edge("missing_clause_detection", "merge_results")

    graph.add_conditional_edges(
        "merge_results",
        _route_after_errors,
        {"continue": "verify_evidence", "stop": END},
    )
    graph.add_conditional_edges(
        "verify_evidence",
        _route_after_errors,
        {"continue": "generate_summary", "stop": END},
    )
    graph.add_conditional_edges(
        "generate_summary",
        _route_after_errors,
        {"continue": "calculate_overview", "stop": END},
    )
    graph.add_conditional_edges(
        "calculate_overview",
        _route_after_errors,
        {"continue": "save_results", "stop": END},
    )
    graph.add_conditional_edges(
        "save_results",
        _route_after_save,
        {"continue": "generate_pdf", "stop": END},
    )
    graph.add_edge("generate_pdf", END)

    return graph.compile()


def run_contract_analysis(
    document_id: str,
    filename: str,
    file_path: str,
    file_type: str,
    runtime_config: dict[str, Any] | None = None,
) -> LegalEaseState:
    """Execute the full LegalEase LangGraph analysis pipeline for one document."""
    workflow = build_legalease_workflow()
    initial_state: LegalEaseState = {
        "document_id": document_id,
        "filename": filename,
        "file_path": file_path,
        "file_type": file_type,
        "processing_errors": [],
        "llm_telemetry": [],
        "db_saved": False,
        "pdf_generated": False,
        "runtime_config": runtime_config or {},
    }
    return workflow.invoke(initial_state)

