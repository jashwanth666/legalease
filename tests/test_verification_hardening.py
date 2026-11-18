"""Grounded evidence verification hardening tests.

Verifies:
1. Exact source location verification for PDF (cross-page mismatch rejection).
2. Exact source location verification for DOCX (cross-paragraph mismatch rejection).
3. 4 distinct verification checks: quote_exists, exact_location_valid, value_supported, interpretation_grounded.
4. Comprehensive verification summary metrics.
"""

import pytest

from backend.agents.summary_agent import SummaryAgent


def test_pdf_cross_page_citation_rejection():
    """If a quote exists on Page 1 but is cited as Page 2, it must be marked unverified with an explicit note."""
    pages = [
        {"page_number": 1, "location_type": "pdf_page", "text": "This agreement shall be governed by the laws of New York."},
        {"page_number": 2, "location_type": "pdf_page", "text": "Signatures and execution block."},
    ]
    clauses = [
        {
            "clause_id": "CL-001",
            "page_number": 1,
            "location_type": "pdf_page",
            "original_text": "This agreement shall be governed by the laws of New York.",
        }
    ]

    # Citation mistakenly cites Page 2
    metadata = {
        "governing_law_and_jurisdiction": {
            "value": "New York",
            "source_quote": "This agreement shall be governed by the laws of New York.",
            "page_number": 2,  # Cited as page 2, actually on page 1!
            "location_type": "pdf_page",
            "is_missing": False,
        }
    }

    result = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=metadata,
        extracted_text="This agreement shall be governed by the laws of New York.\n\nSignatures and execution block.",
    )

    item = metadata["governing_law_and_jurisdiction"]
    assert item["verified"] is False
    checks = item["verification_checks"]
    assert checks["quote_exists"] is True
    assert checks["exact_location_valid"] is False
    assert checks["value_supported"] is True
    assert "page 1" in item["notes"].lower()
    assert "not on cited page 2" in item["notes"].lower()
    assert result["all_verified"] is False


def test_docx_cross_paragraph_citation_rejection():
    """If a quote exists in paragraph 2 but is cited as paragraph 8, it must be marked unverified with an explicit note."""
    pages = [
        {
            "location_type": "docx_paragraph",
            "blocks": [
                {"paragraph_index": 1, "text": "1. Preamble and background."},
                {"paragraph_index": 2, "text": "2. Either party may terminate with 60 days notice."},
                {"paragraph_index": 8, "text": "8. Miscellaneous and counter parts."},
            ],
        }
    ]
    clauses = [
        {
            "clause_id": "CL-002",
            "paragraph_index": 2,
            "location_type": "docx_paragraph",
            "original_text": "2. Either party may terminate with 60 days notice.",
        }
    ]

    # Citation mistakenly claims paragraph 8
    metadata = {
        "notice_period": {
            "value": "60 days",
            "source_quote": "Either party may terminate with 60 days notice.",
            "paragraph_index": 8,  # Cited as paragraph 8, actually in paragraph 2!
            "location_type": "docx_paragraph",
            "is_missing": False,
        }
    }

    result = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=metadata,
        extracted_text="1. Preamble\n2. Either party may terminate with 60 days notice.\n8. Miscellaneous",
    )

    item = metadata["notice_period"]
    assert item["verified"] is False
    checks = item["verification_checks"]
    assert checks["quote_exists"] is True
    assert checks["exact_location_valid"] is False
    assert checks["value_supported"] is True
    assert "paragraph 2" in item["notes"].lower()
    assert "not in cited paragraph 8" in item["notes"].lower()
    assert result["all_verified"] is False


def test_risk_finding_four_verification_checks():
    """Verify that risk findings track quote_exists, exact_location_valid, source_clause_matched, interpretation_grounded."""
    pages = [{"page_number": 1, "location_type": "pdf_page", "text": "Unlimited liability clause text."}]
    clauses = [
        {
            "clause_id": "CL-010",
            "page_number": 1,
            "location_type": "pdf_page",
            "original_text": "Unlimited liability clause text.",
        }
    ]
    risks = [
        {
            "clause_id": "CL-010",
            "original_clause": "Unlimited liability clause text.",
            "page_number": 1,
            "location_type": "pdf_page",
            "explanation": "Clause imposes unlimited aggregate liability exposure.",
            "risk_level": "critical",
            "finding_type": "detected_risk",
        }
    ]

    res = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=risks,
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata={},
        extracted_text="Unlimited liability clause text.",
    )

    finding = risks[0]
    assert finding["verified"] is True
    assert finding["verification_checks"]["quote_exists"] is True
    assert finding["verification_checks"]["exact_location_valid"] is True
    assert finding["verification_checks"]["source_clause_matched"] is True
    assert finding["verification_checks"]["interpretation_grounded"] is True
    assert res["all_verified"] is True
    assert res["verified_risk_count"] == 1
    assert res["unverified_count"] == 0


def test_risk_finding_substantive_reasoning_rejection():
    """Verify that an explanation is rejected if its legal claims are not substantively discussed in the clause."""
    pages = [{"page_number": 1, "location_type": "pdf_page", "text": "Confidential information shall be kept secret."}]
    clauses = [
        {
            "clause_id": "CL-020",
            "page_number": 1,
            "location_type": "pdf_page",
            "original_text": "Confidential information shall be kept secret.",
        }
    ]
    # Finding hallucinates a liability cap on a confidentiality clause
    risks = [
        {
            "clause_id": "CL-020",
            "original_clause": "Confidential information shall be kept secret.",
            "page_number": 1,
            "location_type": "pdf_page",
            "risk_title": "Severe Liability Cap",
            "category": "liability_cap",
            "explanation": "Imposes an aggregate liability damages cap limiting contractor recovery.",
            "risk_level": "high",
            "finding_type": "detected_risk",
        }
    ]

    res = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=risks,
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata={},
        extracted_text="Confidential information shall be kept secret.",
    )

    finding = risks[0]
    assert finding["verified"] is False
    assert finding["verification_checks"]["quote_exists"] is True
    assert finding["verification_checks"]["exact_location_valid"] is True
    # Substantive reasoning must be FALSE because the clause does not discuss liability!
    assert finding["verification_checks"]["interpretation_grounded"] is False
    assert "not substantively discussed" in finding["verification_note"]
    assert res["all_verified"] is False
    assert res["unverified_count"] == 1


def test_uncertain_finding_interpretation_not_grounded():
    """Uncertain findings must have interpretation_grounded=False and verified=False."""
    pages = [{"page_number": 1, "location_type": "pdf_page", "text": "Some ambiguous contractual wording."}]
    clauses = [
        {
            "clause_id": "CL-030",
            "page_number": 1,
            "location_type": "pdf_page",
            "original_text": "Some ambiguous contractual wording.",
        }
    ]
    risks = [
        {
            "clause_id": "CL-030",
            "original_clause": "Some ambiguous contractual wording.",
            "page_number": 1,
            "location_type": "pdf_page",
            "explanation": "Wording is vague and requires attorney clarification.",
            "risk_level": "uncertain",
            "finding_type": "uncertain_finding",
        }
    ]

    res = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=risks,
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata={},
        extracted_text="Some ambiguous contractual wording.",
    )

    finding = risks[0]
    assert finding["verified"] is False
    assert finding["verification_checks"]["interpretation_grounded"] is False
