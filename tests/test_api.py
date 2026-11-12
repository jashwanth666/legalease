"""End-to-end API, LangGraph workflow, SQLite persistence, and PDF report tests."""

from pathlib import Path

from fastapi.testclient import TestClient
import pymupdf as fitz
import pytest

from backend.agents.summary_agent import SummaryAgent
from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app


class _APITestSettings(Settings):
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


@pytest.fixture()
def api_client(tmp_path: Path):
    db_path = tmp_path / "api_legalease.db"
    test_settings = _APITestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
    )
    test_settings.ensure_directories()
    configure_database(test_settings.database_url)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as client:
        yield client, test_settings

    app.dependency_overrides.clear()


def test_missing_clause_detection_and_evidence_verification():
    classified = [
        {"clause_id": "CL-001", "category": "Definitions", "confidence": 0.9, "uncertain": False},
        {"clause_id": "CL-002", "category": "Confidentiality", "confidence": 0.9, "uncertain": False},
    ]
    missing = SummaryAgent.detect_missing_clauses("NDA", classified)
    missing_cats = {item["category"] for item in missing["missing_categories"]}
    assert "Termination" in missing_cats
    assert "Dispute Resolution" in missing_cats
    assert "Confidentiality" not in missing_cats

    # Evidence verification catches tampered reference wording
    pages = [{"page_number": 1, "text": "Clause text"}]
    clauses = [{"clause_id": "CL-001", "original_text": "Clause text", "page_number": 1}]
    risks = [
        {
            "clause_id": "CL-001",
            "original_clause": "Clause text",
            "page_number": 1,
            "explanation": "Explained",
        }
    ]
    comparisons = [
        {
            "clause_id": "CL-001",
            "reference_clause": "Invented wording not in retrieval",
            "reference_source": "nda_reference.txt",
        }
    ]
    verification = SummaryAgent.verify_evidence(
        pages=pages,
        clauses=clauses,
        classified_clauses=classified,
        risk_results=risks,
        retrieved_references={"CL-001": [{"text": "Actual reference", "reference_source": "nda_reference.txt"}]},
        comparison_results=comparisons,
        missing_clauses=missing,
    )
    assert risks[0]["verified"] is True
    assert comparisons[0]["verified"] is False
    assert verification["all_verified"] is False


def test_full_end_to_end_langgraph_and_pdf_report_pipeline(api_client):
    client, test_settings = api_client
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_service_agreement.pdf"
    )
    assert sample_pdf.exists()

    # 1. Upload
    with sample_pdf.open("rb") as f:
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("sample_service_agreement.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document_id"]
    assert upload_resp.json()["processing_status"] == "uploaded"

    # Analysis should not exist before explicit user confirmation
    pre_analysis = client.get(f"/api/analysis/{doc_id}")
    assert pre_analysis.status_code == 409

    # 2. Trigger LangGraph analysis
    analyze_resp = client.post(f"/api/analyze/{doc_id}")
    assert analyze_resp.status_code == 200
    analysis = analyze_resp.json()
    assert analysis["document_id"] == doc_id
    assert analysis["processing_status"] == "analyzed"
    assert analysis["detected_contract_type"] == "Service Agreement"
    assert analysis["analysis_mode"] == "deterministic_fallback"
    assert analysis["overall_risk_score"] > 0
    assert analysis["risk_distribution"]["total"] == 9
    assert len(analysis["risk_findings"]) == 9
    assert analysis["verified_findings"]["all_verified"] is True
    assert analysis["report_available"] is True

    # Missing clauses for Service Agreement (Dispute Resolution & Jurisdiction are missing in sample)
    missing_cats = {
        m["category"] for m in analysis["missing_clauses"].get("missing_categories", [])
    }
    assert "Dispute Resolution" in missing_cats
    assert "Jurisdiction" in missing_cats

    # 3. GET /api/analysis/{document_id}
    get_analysis_resp = client.get(f"/api/analysis/{doc_id}")
    assert get_analysis_resp.status_code == 200
    assert get_analysis_resp.json()["overall_risk_score"] == analysis["overall_risk_score"]

    # 4. GET /api/clauses/{document_id}
    clauses_resp = client.get(f"/api/clauses/{doc_id}")
    assert clauses_resp.status_code == 200
    assert clauses_resp.json()["count"] == 9
    assert all(c["classification_source"] != "gemini" for c in clauses_resp.json()["clauses"])

    # 5. GET /api/compare/{document_id}
    compare_resp = client.get(f"/api/compare/{doc_id}")
    assert compare_resp.status_code == 200
    comp_data = compare_resp.json()
    assert comp_data["count"] >= 1
    assert any(c["reference_source"] == "service_reference.txt" for c in comp_data["comparisons"])

    # 6. GET /api/reports & GET /api/report/{document_id}
    reports_list = client.get("/api/reports")
    assert reports_list.status_code == 200
    assert any(r["document_id"] == doc_id for r in reports_list.json())

    pdf_resp = client.get(f"/api/report/{doc_id}")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF-")

    pdf_doc = fitz.open(stream=pdf_resp.content, filetype="pdf")
    pdf_text = "\n".join(page.get_text() for page in pdf_doc)
    pdf_doc.close()
    assert "LegalEase" in pdf_text
    assert doc_id in pdf_text
    assert "Disclaimer" in pdf_text

    # 7. DELETE /api/documents/{document_id} cleans up file, extracted JSON, and PDF report
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert not (test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf").exists()

