"""Unit and integration tests for Contract Metadata Extraction and Evidence Verification."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.agents.metadata_agent import MetadataAgent
from backend.agents.summary_agent import SummaryAgent
from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app
from backend.schemas.metadata import ContractMetadata, MetadataItem

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_contracts"


class _TestSettings(Settings):
    test_root: Path

    @property
    def upload_dir(self) -> Path:
        return self.test_root / "uploads"

    @property
    def extracted_dir(self) -> Path:
        return self.test_root / "extracted"

    @property
    def vectorstore_dir(self) -> Path:
        return self.test_root / "vectorstore"

    @property
    def reports_dir(self) -> Path:
        return self.test_root / "reports"


@pytest.fixture
def test_client(tmp_path: Path):
    db_path = tmp_path / "metadata_test.db"
    settings = _TestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
    )
    for p in (
        settings.upload_dir,
        settings.extracted_dir,
        settings.vectorstore_dir,
        settings.reports_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)

    configure_database(settings.database_url)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    app.dependency_overrides.clear()


def test_metadata_pydantic_schema_validation():
    """Verify that ContractMetadata enforces the 16 fields and defaults to unverified."""
    item = MetadataItem(
        field_name="governing_law_and_jurisdiction",
        value="State of New York",
        source_quote="This Agreement shall be governed by the laws of the State of New York.",
        page_number=2,
        location_type="pdf_page",
        confidence=0.95,
        verified=False,
    )
    assert item.value == "State of New York"
    assert item.verified is False
    assert item.is_missing is False

    missing_item = MetadataItem(
        field_name="contract_value",
        value=None,
        is_missing=True,
        confidence=0.0,
    )
    assert missing_item.value is None
    assert missing_item.is_missing is True
    assert missing_item.verified is False


def test_metadata_agent_deterministic_extraction_nda():
    """Verify deterministic fallback extraction on typical NDA content with verified=False default."""
    sample_text = (
        "MUTUAL NON-DISCLOSURE AGREEMENT\n"
        "This Mutual Non-Disclosure Agreement (the 'Agreement') is entered into as of March 15, 2024 (the 'Effective Date'),\n"
        "by and between Acme Corporation, a Delaware corporation ('Disclosing Party'), and Beta Technologies LLC ('Receiving Party').\n\n"
        "1. Term and Duration. This Agreement shall continue in effect for a term of 2 years from the Effective Date.\n"
        "The confidentiality obligations hereunder shall survive for a period of 5 years following termination.\n\n"
        "2. Termination. Either party may terminate upon 30 days prior written notice.\n\n"
        "3. Governing Law. This Agreement shall be construed in accordance with the laws of Delaware.\n"
        "Any dispute arising shall be resolved by binding arbitration under the rules of the American Arbitration Association.\n"
    )
    clauses = [
        {
            "clause_id": "C001",
            "title": "Title and Parties",
            "category": "Definitions",
            "original_text": sample_text[:300],
            "page_number": 1,
            "location_type": "pdf_page",
        },
        {
            "clause_id": "C002",
            "title": "Term and Duration",
            "category": "Termination",
            "original_text": "This Agreement shall continue in effect for a term of 2 years from the Effective Date. The confidentiality obligations hereunder shall survive for a period of 5 years.",
            "page_number": 1,
            "location_type": "pdf_page",
        },
        {
            "clause_id": "C003",
            "title": "Governing Law and Arbitration",
            "category": "Jurisdiction",
            "original_text": "This Agreement shall be construed in accordance with the laws of Delaware. Any dispute arising shall be resolved by binding arbitration under the rules of the American Arbitration Association.",
            "page_number": 1,
            "location_type": "pdf_page",
        },
    ]

    agent = MetadataAgent(llm_service=None)
    metadata = agent._extract_deterministic(
        full_text=sample_text,
        clauses=clauses,
        document_id="DOC-TEST-NDA",
        filename="mutual_nda.pdf",
    )

    assert metadata.document_id == "DOC-TEST-NDA"
    assert metadata.extraction_source == "deterministic_fallback"

    # All fields must default to verified=False at extraction time!
    for f_name in (
        "contract_title_and_type",
        "party_names_and_roles",
        "effective_date",
        "contract_duration",
        "notice_period",
        "governing_law_and_jurisdiction",
        "confidentiality_period",
        "dispute_resolution_method",
    ):
        item = getattr(metadata, f_name)
        assert item.verified is False, f"Field '{f_name}' should default to verified=False at extraction."

    # Value accuracy checks
    assert "NDA" in str(metadata.contract_title_and_type.value)
    assert metadata.party_names_and_roles.value is not None
    assert "March 15, 2024" in str(metadata.effective_date.value)
    assert "2 years" in str(metadata.contract_duration.value)
    assert "30 days" in str(metadata.notice_period.value)
    assert "Delaware" in str(metadata.governing_law_and_jurisdiction.value)
    assert "5 years" in str(metadata.confidentiality_period.value)
    assert "arbitration" in str(metadata.dispute_resolution_method.value).lower()

    # Zero hallucination check: NDA has no contract value
    assert metadata.contract_value.is_missing is True
    assert metadata.contract_value.value is None


def test_metadata_regex_patterns_standalone():
    """Verify regex extractions migrated from temporary scratch testing."""
    text = (
        "This Mutual Non-Disclosure Agreement is entered into as of March 15, 2024,\n"
        "by and between Acme Corporation, a Delaware corporation, and Beta Technologies LLC.\n"
        "The confidentiality obligations hereunder shall survive for a period of 5 years following termination."
    )
    clauses = [{"clause_id": "C001", "original_text": text, "page_number": 1}]
    agent = MetadataAgent(llm_service=None)
    meta = agent._extract_deterministic(text, clauses, "D-1", "test.pdf")

    assert meta.party_names_and_roles.value == ["Acme Corporation", "Beta Technologies LLC"]
    assert meta.effective_date.value == "March 15, 2024"
    assert meta.confidentiality_period.value == "5 years following termination"


def test_evidence_verification_fabricated_quotation():
    """Verify that a quotation not present in the contract text is flagged unverified."""
    sample_text = "This is a simple contract entered into on June 1, 2025."
    clauses = [{"clause_id": "C001", "original_text": sample_text, "page_number": 1}]

    metadata_dict = {
        "liability_limitations": {
            "value": "Unlimited liability",
            "source_quote": "This clause does not exist anywhere in the text of the contract.",
            "page_number": 1,
            "location_type": "pdf_page",
            "is_missing": False,
        }
    }

    verification = SummaryAgent.verify_evidence(
        pages=[{"page_number": 1}],
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=metadata_dict,
        extracted_text=sample_text,
    )

    assert metadata_dict["liability_limitations"]["verified"] is False
    assert "source quote not found verbatim" in metadata_dict["liability_limitations"]["notes"].lower()
    assert verification["all_verified"] is False


def test_evidence_verification_incorrect_value_with_valid_quotation():
    """Verify that an incorrect metadata value is flagged unverified even when the cited quotation exists verbatim."""
    sample_text = (
        "Section 7. Limitation of Liability. "
        "In no event shall either party's aggregate liability exceed the sum of $10,000 USD."
    )
    clauses = [{"clause_id": "C001", "original_text": sample_text, "page_number": 1}]

    # The quote exists verbatim in the text, BUT the extracted value claims 'Unlimited liability'
    metadata_dict = {
        "liability_limitations": {
            "value": "Unlimited liability",
            "source_quote": "In no event shall either party's aggregate liability exceed the sum of $10,000 USD.",
            "page_number": 1,
            "location_type": "pdf_page",
            "is_missing": False,
        },
        "governing_law_and_jurisdiction": {
            "value": "State of California",
            "source_quote": "Section 7. Limitation of Liability.",
            "page_number": 1,
            "location_type": "pdf_page",
            "is_missing": False,
        },
        "contract_value": {
            "value": "$500,000",
            "source_quote": "In no event shall either party's aggregate liability exceed the sum of $10,000 USD.",
            "page_number": 1,
            "location_type": "pdf_page",
            "is_missing": False,
        },
    }

    verification = SummaryAgent.verify_evidence(
        pages=[{"page_number": 1}],
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=metadata_dict,
        extracted_text=sample_text,
    )

    # 1. 'Unlimited liability' is not supported by a $10,000 cap quote
    assert metadata_dict["liability_limitations"]["verified"] is False
    assert "not supported" in metadata_dict["liability_limitations"]["notes"].lower()

    # 2. 'State of California' is not supported by a title quote
    assert metadata_dict["governing_law_and_jurisdiction"]["verified"] is False
    assert "not mentioned in cited quote" in metadata_dict["governing_law_and_jurisdiction"]["notes"].lower()

    # 3. '$500,000' is not supported by a $10,000 quote
    assert metadata_dict["contract_value"]["verified"] is False
    assert "numeric quantity" in metadata_dict["contract_value"]["notes"].lower()

    assert verification["all_verified"] is False


def test_evidence_verification_pdf_location_boundaries():
    """Verify that PDF page numbers are strictly validated against extracted pages."""
    sample_text = "Governed by the laws of Delaware."
    clauses = [{"clause_id": "C001", "original_text": sample_text, "page_number": 1}]
    pages = [{"page_number": 1, "text": sample_text}]

    # Case A: Valid page 1
    valid_meta = {
        "governing_law_and_jurisdiction": {
            "value": "Delaware",
            "source_quote": "Governed by the laws of Delaware.",
            "page_number": 1,
            "location_type": "pdf_page",
            "is_missing": False,
        }
    }
    v_valid = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=valid_meta,
        extracted_text=sample_text,
    )
    assert valid_meta["governing_law_and_jurisdiction"]["verified"] is True
    assert v_valid["all_verified"] is True

    # Case B: Out-of-bounds page 999
    invalid_meta = {
        "governing_law_and_jurisdiction": {
            "value": "Delaware",
            "source_quote": "Governed by the laws of Delaware.",
            "page_number": 999,
            "location_type": "pdf_page",
            "is_missing": False,
        }
    }
    v_invalid = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=invalid_meta,
        extracted_text=sample_text,
    )
    assert invalid_meta["governing_law_and_jurisdiction"]["verified"] is False
    assert "invalid location" in invalid_meta["governing_law_and_jurisdiction"]["notes"].lower()
    assert v_invalid["all_verified"] is False


def test_evidence_verification_docx_paragraph_boundaries():
    """Verify that DOCX paragraph indices are strictly validated against actual extracted paragraphs."""
    sample_text = "Either party may terminate upon 30 days written notice."
    clauses = [
        {
            "clause_id": "C001",
            "original_text": sample_text,
            "paragraph_index": 5,
            "location_type": "docx_paragraph",
        }
    ]
    pages = [
        {
            "location_type": "docx_paragraph",
            "blocks": [{"paragraph_index": 1}, {"paragraph_index": 3}, {"paragraph_index": 5}],
        }
    ]

    # Case A: Valid paragraph index 5
    valid_meta = {
        "notice_period": {
            "value": "30 days",
            "source_quote": "Either party may terminate upon 30 days written notice.",
            "paragraph_index": 5,
            "location_type": "docx_paragraph",
            "is_missing": False,
        }
    }
    v_valid = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=valid_meta,
        extracted_text=sample_text,
    )
    assert valid_meta["notice_period"]["verified"] is True
    assert v_valid["all_verified"] is True

    # Case B: Out-of-bounds paragraph index 9999
    invalid_meta = {
        "notice_period": {
            "value": "30 days",
            "source_quote": "Either party may terminate upon 30 days written notice.",
            "paragraph_index": 9999,
            "location_type": "docx_paragraph",
            "is_missing": False,
        }
    }
    v_invalid = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=[],
        retrieved_references={},
        comparison_results=[],
        missing_clauses={"missing_categories": []},
        contract_metadata=invalid_meta,
        extracted_text=sample_text,
    )
    assert invalid_meta["notice_period"]["verified"] is False
    assert "invalid location" in invalid_meta["notice_period"]["notes"].lower()
    assert v_invalid["all_verified"] is False


def test_evidence_verification_insufficient_evidence_accounting():
    """Verify that comparisons marked insufficient_evidence increment unverified_count and set all_verified=False."""
    pages = [{"page_number": 1, "text": "Clause text"}]
    clauses = [{"clause_id": "CL-001", "original_text": "Clause text", "page_number": 1}]
    risks = [
        {
            "clause_id": "CL-001",
            "original_clause": "Clause text",
            "page_number": 1,
            "explanation": "Valid risk explanation",
        }
    ]
    comparisons = [
        {
            "clause_id": "CL-001",
            "reference_clause": "",
            "reference_source": "template_nda.txt",
            "insufficient_evidence": True,
        }
    ]

    verification = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=[],
        risk_results=risks,
        retrieved_references={},
        comparison_results=comparisons,
        missing_clauses={"missing_categories": []},
    )

    assert comparisons[0]["verified"] is False
    assert "insufficient reference evidence" in comparisons[0]["verification_note"].lower()
    # unverified_count must be at least 1 and all_verified must be False!
    assert verification["unverified_count"] >= 1
    assert verification["all_verified"] is False


def test_metadata_api_endpoint(test_client):
    """End-to-end integration test verifying GET /api/metadata/{id} after contract analysis."""
    client, _ = test_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"
    assert pdf_path.exists()

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    assert up.status_code in (200, 201)
    doc_id = up.json()["document_id"]

    # Run analysis
    an = client.post(f"/api/analyze/{doc_id}?wait=true")
    assert an.status_code == 200

    # Query metadata endpoint
    meta_resp = client.get(f"/api/metadata/{doc_id}")
    assert meta_resp.status_code == 200
    meta_data = meta_resp.json()

    assert meta_data["document_id"] == doc_id
    assert "metadata" in meta_data
    fields = meta_data["metadata"]
    assert "contract_title_and_type" in fields
    assert "party_names_and_roles" in fields
    assert "effective_date" in fields
    assert "confidentiality_period" in fields

    # Query full analysis payload to verify metadata is included
    analysis_resp = client.get(f"/api/analysis/{doc_id}")
    assert analysis_resp.status_code == 200
    analysis_payload = analysis_resp.json()
    assert "contract_metadata" in analysis_payload
    assert analysis_payload["contract_metadata"]["document_id"] == doc_id
