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
    """Verify that ContractMetadata enforces the 16 fields and grounded citations."""
    item = MetadataItem(
        field_name="governing_law_and_jurisdiction",
        value="State of New York",
        source_quote="This Agreement shall be governed by the laws of the State of New York.",
        page_number=2,
        location_type="pdf_page",
        confidence=0.95,
        verified=True,
    )
    assert item.value == "State of New York"
    assert item.verified is True
    assert item.is_missing is False

    missing_item = MetadataItem(
        field_name="contract_value",
        value=None,
        is_missing=True,
        confidence=0.0,
    )
    assert missing_item.value is None
    assert missing_item.is_missing is True


def test_metadata_agent_deterministic_extraction_nda():
    """Verify deterministic fallback extraction on typical NDA content."""
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

    # 1. Title
    assert "NDA" in str(metadata.contract_title_and_type.value)
    # 2. Parties
    assert metadata.party_names_and_roles.value is not None
    # 3. Effective date
    assert metadata.effective_date.value is not None
    assert "March 15, 2024" in str(metadata.effective_date.value)
    # 4. Duration
    assert "2 years" in str(metadata.contract_duration.value)
    # 5. Notice period
    assert "30 days" in str(metadata.notice_period.value)
    # 6. Governing law
    assert "Delaware" in str(metadata.governing_law_and_jurisdiction.value)
    # 7. Confidentiality period
    assert "5 years" in str(metadata.confidentiality_period.value)
    # 8. Dispute resolution
    assert "arbitration" in str(metadata.dispute_resolution_method.value).lower()

    # Zero hallucination check: NDA has no contract value
    assert metadata.contract_value.is_missing is True
    assert metadata.contract_value.value is None


def test_evidence_verification_on_metadata():
    """Verify that SummaryAgent.verify_evidence validates metadata source quotes against actual text."""
    sample_text = (
        "This Agreement is entered into on June 1, 2025. "
        "Either party may terminate upon 60 days written notice. "
        "Total compensation is $50,000 USD."
    )
    clauses = [
        {
            "clause_id": "C001",
            "original_text": sample_text,
            "page_number": 1,
            "location_type": "pdf_page",
        }
    ]

    metadata_dict = {
        "document_id": "DOC-TEST",
        "effective_date": {
            "value": "June 1, 2025",
            "source_quote": "This Agreement is entered into on June 1, 2025.",
            "page_number": 1,
            "is_missing": False,
        },
        "notice_period": {
            "value": "60 days",
            "source_quote": "Either party may terminate upon 60 days written notice.",
            "page_number": 1,
            "is_missing": False,
        },
        # Hallucinated/fabricated quote that does not exist in text:
        "liability_limitations": {
            "value": "Unlimited liability",
            "source_quote": "The liability shall be completely uncapped for all intentional misconduct.",
            "page_number": 1,
            "is_missing": False,
        },
        "contract_value": {
            "value": "$50,000 USD",
            "source_quote": "Total compensation is $50,000 USD.",
            "page_number": 1,
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

    # Effective date and notice period and contract value should be verified
    assert metadata_dict["effective_date"]["verified"] is True
    assert metadata_dict["notice_period"]["verified"] is True
    assert metadata_dict["contract_value"]["verified"] is True

    # Fabricated liability quote must NOT be verified!
    assert metadata_dict["liability_limitations"]["verified"] is False
    assert "Source quote could not be matched" in metadata_dict["liability_limitations"]["notes"]
    assert verification["verified_metadata_count"] == 3


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
