"""Tests for PDF/DOCX extraction, page-number preservation, clause splitting, and classification."""

from pathlib import Path

import docx
import pymupdf as fitz

from backend.agents.classification_agent import ClassificationAgent
from backend.agents.extraction_agent import ExtractionAgent
from backend.ingestion.clause_splitter import split_pages_into_clauses
from backend.ingestion.document_loader import extract_document_text
from backend.schemas.clause import GeminiBatchClassification, GeminiSingleClassification
from backend.services.llm_service import LLMService


def test_extract_sample_service_agreement_preserves_pages_and_headings(tmp_path: Path):
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_service_agreement.pdf"
    )
    agent = ExtractionAgent()
    result = agent.run(
        file_path=sample_pdf,
        document_id="DOC-TESTPDF",
        filename="sample_service_agreement.pdf",
        file_type="pdf",
        extracted_dir=tmp_path,
    )

    assert result["document_id"] == "DOC-TESTPDF"
    assert result["page_count"] == 3
    assert result["ocr_required"] is False
    assert [p["page_number"] for p in result["pages"]] == [1, 2, 3]
    assert "Payment Terms" in result["pages"][0]["text"]
    assert "Limitation of Liability" in result["pages"][1]["text"]
    assert "Force Majeure" in result["pages"][2]["text"]

    reloaded = agent.get_extracted("DOC-TESTPDF", tmp_path)
    assert reloaded is not None
    assert reloaded["page_count"] == 3


def test_detect_scanned_or_blank_pdf_requires_ocr(tmp_path: Path):
    blank_pdf = tmp_path / "scanned.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(str(blank_pdf))
    pdf.close()

    result = extract_document_text(
        file_path=blank_pdf,
        document_id="DOC-SCAN",
        original_filename="scanned.pdf",
        file_type="pdf",
    )

    assert result["ocr_required"] is True
    assert result["warning"] is not None
    assert "OCR" in result["warning"]


def test_extract_docx_with_page_break_and_tables(tmp_path: Path):
    docx_path = tmp_path / "contract.docx"
    doc = docx.Document()
    doc.add_heading("1. Confidentiality", level=1)
    doc.add_paragraph("Receiving Party shall keep information confidential.")
    doc.add_page_break()
    doc.add_heading("2. Payment Schedule", level=1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Phase"
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).text = "Initial"
    table.cell(1, 1).text = "$2,500"
    doc.save(str(docx_path))

    result = extract_document_text(
        file_path=docx_path,
        document_id="DOC-DOCX1",
        original_filename="contract.docx",
        file_type="docx",
    )

    assert result["ocr_required"] is False
    # DOCX never invents fixed page numbers; uses paragraph references instead
    assert result["page_count"] == 0
    assert result["location_mode"] == "docx_paragraph"
    assert result["pages"][0]["page_number"] is None
    assert result["pages"][0]["location_type"] == "docx_paragraph"
    assert "Confidentiality" in result["pages"][0]["text"]
    assert "Phase | Amount" in result["pages"][0]["text"]
    assert "Initial | $2,500" in result["pages"][0]["text"]

    clauses = split_pages_into_clauses(result["pages"])
    assert len(clauses) == 2
    assert all(c.page_number is None for c in clauses)
    assert all(c.location_type == "docx_paragraph" for c in clauses)
    assert clauses[0].paragraph_index == 1
    assert clauses[1].paragraph_index > clauses[0].paragraph_index


def test_clause_splitting_preserves_full_text_and_page_numbers():
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_service_agreement.pdf"
    )
    extracted = extract_document_text(
        file_path=sample_pdf,
        document_id="DOC-SPLIT",
        original_filename="sample_service_agreement.pdf",
        file_type="pdf",
    )
    clauses = split_pages_into_clauses(extracted["pages"])

    assert len(clauses) == 9
    assert clauses[0].clause_id == "CL-001"
    assert clauses[0].page_number == 1
    assert clauses[4].category == "Liability"
    assert clauses[4].page_number == 2
    assert "ONE HUNDRED DOLLARS ($100)" in clauses[4].original_text
    assert clauses[8].category == "Force Majeure"
    assert clauses[8].page_number == 3


def test_classification_fallback_when_gemini_key_missing():
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_nda.pdf"
    )
    extracted = extract_document_text(
        file_path=sample_pdf,
        document_id="DOC-NDA",
        original_filename="sample_nda.pdf",
        file_type="pdf",
    )
    clauses = split_pages_into_clauses(extracted["pages"])

    agent = ClassificationAgent(llm_service=LLMService(api_key=""))
    classifications, mode = agent.classify_clauses(clauses)

    assert mode == "deterministic_fallback"
    assert len(classifications) == len(clauses)
    assert all(c.classification_source != "gemini" for c in classifications)
    categories = {c.category for c in classifications}
    assert "Confidentiality" in categories
    assert "Non-Compete" in categories
    assert "Jurisdiction" in categories


def test_classification_with_mocked_gemini_structured_output():
    clauses = split_pages_into_clauses(
        [
            {
                "page_number": 4,
                "headings": ["7. Termination"],
                "text": "7. Termination\n\nEither party may terminate upon 30 days written notice.",
            }
        ]
    )

    class _MockLLM(LLMService):
        @property
        def is_available(self) -> bool:
            return True

        def invoke_structured(self, system_prompt, user_prompt, schema, temperature=0.1):
            return GeminiBatchClassification(
                classifications=[
                    GeminiSingleClassification(
                        clause_id=clauses[0].clause_id,
                        category="Termination",
                        description="Explains how either party can terminate the agreement.",
                        confidence=0.95,
                    )
                ]
            )

    agent = ClassificationAgent(llm_service=_MockLLM(api_key="fake-key"))
    classifications, mode = agent.classify_clauses(clauses)

    assert mode == "gemini"
    assert len(classifications) == 1
    assert classifications[0].category == "Termination"
    assert classifications[0].confidence == 0.95
    assert classifications[0].classification_source == "gemini"


def test_clause_splitting_handles_roman_numerals_inline_caps_multipage_and_signatures():
    pages = [
        {
            "page_number": 1,
            "location_type": "pdf_page",
            "headings": [],
            "text": (
                "SERVICE AGREEMENT\n\n"
                "Page 1 of 3\n\n"
                "IV. CONFIDENTIALITY\n\n"
                "Receiving Party shall hold all proprietary information in strict confidence.\n\n"
                "8. TERMINATION Either party may terminate upon 30 days notice. "
                "9. LIMITATION OF LIABILITY Neither party shall be liable for indirect damages"
            ),
        },
        {
            "page_number": 2,
            "location_type": "pdf_page",
            "headings": [],
            "text": (
                "and total aggregate liability is capped at twelve months of fees.\n\n"
                "IN WITNESS WHEREOF, the parties have executed this Agreement.\n\n"
                "By: ______________________\n\n"
                "Date: ______________________"
            ),
        },
    ]
    clauses = split_pages_into_clauses(pages)
    assert len(clauses) == 3
    assert clauses[0].title == "IV. CONFIDENTIALITY"
    assert clauses[0].category == "Confidentiality"
    assert clauses[1].title == "8. TERMINATION"
    assert clauses[2].title == "9. LIMITATION OF LIABILITY"
    # Multi-page clause continuation preserves start page 1 and end page 2 plus complete text
    assert clauses[2].page_number == 1
    assert clauses[2].end_page_number == 2
    assert "twelve months of fees" in clauses[2].original_text
    # Signature block boilerplate is excluded
    assert not any("WITNESS WHEREOF" in c.original_text for c in clauses)


def test_clause_splitting_flags_uncertain_unheaded_prose():
    clauses = split_pages_into_clauses(
        [
            {
                "page_number": 1,
                "location_type": "pdf_page",
                "headings": [],
                "text": "The vendor agrees to cooperate in good faith with customer audits upon advance request.",
            }
        ]
    )
    assert len(clauses) == 1
    assert clauses[0].segmentation_uncertain is True
    assert clauses[0].segmentation_confidence == "medium"
