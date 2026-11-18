"""End-to-end API, LangGraph workflow, SQLite persistence, and PDF report tests."""

import io
from pathlib import Path

import docx
from fastapi.testclient import TestClient
import pymupdf as fitz
import pytest

from backend.agents.summary_agent import SummaryAgent
from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app
from tests.conftest import create_test_user


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

    _, token = create_test_user(secret_key=test_settings.jwt_secret_key)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
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

    # 2. Trigger LangGraph analysis (asynchronous background task returning 202 Accepted)
    analyze_resp = client.post(f"/api/analyze/{doc_id}")
    assert analyze_resp.status_code == 202
    assert analyze_resp.json()["processing_status"] == "queued"

    # Status endpoint reports real-time progress
    status_resp = client.get(f"/api/status/{doc_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["processing_status"] == "analyzed"
    assert status_resp.json()["progress_percent"] == 100

    analysis = client.get(f"/api/analysis/{doc_id}").json()
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


def test_analysis_failure_resets_processing_status_and_allows_retry(api_client, monkeypatch):
    client, _ = api_client
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_nda.pdf"
    )
    with sample_pdf.open("rb") as f:
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("sample_nda.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document_id"]

    # Simulate unexpected crash inside run_contract_analysis
    def _boom(**kwargs):
        raise RuntimeError("Simulated LangGraph crash")

    monkeypatch.setattr("backend.api.analysis.run_contract_analysis", _boom)
    fail_resp = client.post(f"/api/analyze/{doc_id}")
    assert fail_resp.status_code == 202

    # Must NEVER remain stuck in 'processing'
    doc_state = client.get(f"/api/documents/{doc_id}").json()["document"]
    assert doc_state["processing_status"] == "failed"
    assert doc_state["last_error"] is not None

    # Report download must be blocked until analysis succeeds
    assert client.get(f"/api/report/{doc_id}").status_code == 409

    # Restore real workflow and retry
    from backend.graph.workflow import run_contract_analysis as real_run

    monkeypatch.setattr("backend.api.analysis.run_contract_analysis", real_run)
    retry_resp = client.post(f"/api/analyze/{doc_id}")
    assert retry_resp.status_code == 202
    assert client.get(f"/api/status/{doc_id}").json()["processing_status"] == "analyzed"
    assert client.get(f"/api/report/{doc_id}").status_code == 200


def test_pdf_generation_skipped_on_db_save_failure_and_partially_analyzed_on_pdf_failure(
    api_client, monkeypatch
):
    client, test_settings = api_client
    sample_pdf = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "sample_contracts"
        / "sample_nda.pdf"
    )
    with sample_pdf.open("rb") as f:
        doc_id = client.post(
            "/api/upload",
            files={"file": ("sample_nda.pdf", f, "application/pdf")},
        ).json()["document_id"]

    # 1. Fail DB save -> generate_pdf must NOT run
    pdf_called = []
    from backend.graph import nodes as graph_nodes

    orig_save = graph_nodes.save_results_node
    orig_pdf = graph_nodes.generate_pdf_node

    def _fail_save(state):
        return {"db_saved": False, "processing_errors": ["Simulated DB failure"]}

    def _spy_pdf(state):
        pdf_called.append(True)
        return orig_pdf(state)

    monkeypatch.setattr("backend.graph.workflow.save_results_node", _fail_save)
    monkeypatch.setattr("backend.graph.workflow.generate_pdf_node", _spy_pdf)

    resp1 = client.post(f"/api/analyze/{doc_id}")
    assert resp1.status_code == 202
    assert pdf_called == []
    assert not (test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf").exists()
    assert client.get(f"/api/documents/{doc_id}").json()["document"]["processing_status"] == "failed"

    # 2. Restore DB save, fail PDF generation -> status becomes 'partially_analyzed', NOT 'analyzed'
    monkeypatch.setattr("backend.graph.workflow.save_results_node", orig_save)

    def _fail_pdf(state):
        return {"pdf_generated": False, "processing_errors": ["Simulated PDF error"]}

    monkeypatch.setattr("backend.graph.workflow.generate_pdf_node", _fail_pdf)
    resp2 = client.post(f"/api/analyze/{doc_id}")
    assert resp2.status_code == 202
    assert client.get(f"/api/documents/{doc_id}").json()["document"]["processing_status"] == "partially_analyzed"
    assert client.get(f"/api/report/{doc_id}").status_code == 409


def test_docx_end_to_end_with_unicode_and_paragraph_locations(api_client):
    client, _ = api_client
    doc = docx.Document()
    doc.add_heading("1. Confidentiality — Mutual Protection", level=1)
    doc.add_paragraph(
        "Receiving Party shall hold all confidential data in confidence — valued up to ₹500,000 or €5,000."
    )
    doc.add_heading("2. Limitation of Liability", level=1)
    doc.add_paragraph(
        "IN NO EVENT SHALL PROVIDER BE LIABLE FOR INDIRECT DAMAGES AND TOTAL LIABILITY SHALL NOT EXCEED ONE HUNDRED DOLLARS ($100)."
    )
    buf = io.BytesIO()
    doc.save(buf)

    upload = client.post(
        "/api/upload",
        files={
            "file": (
                "unicode_service.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload.status_code == 201
    doc_id = upload.json()["document_id"]
    assert upload.json()["page_count"] == 0

    analyze = client.post(f"/api/analyze/{doc_id}")
    assert analyze.status_code == 202
    payload = client.get(f"/api/analysis/{doc_id}").json()
    assert payload["processing_status"] == "analyzed"
    assert payload["gemini_status"] == "missing_key"
    assert payload["fallback_used"] is True
    assert all(rf["location_type"] == "docx_paragraph" for rf in payload["risk_findings"])
    assert all(rf["page_number"] is None for rf in payload["risk_findings"])

    pdf_resp = client.get(f"/api/report/{doc_id}")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF-")



def test_download_report_returns_404_when_file_missing(api_client):
    """When a report file is deleted from disk and regenerate=False, download must return 404."""
    client, test_settings = api_client
    nda_file = Path("data/sample_contracts/sample_nda.pdf")
    with nda_file.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    client.post(f"/api/analyze/{doc_id}")

    # Delete report from disk
    rep_path = test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf"
    if rep_path.exists():
        rep_path.unlink()

    resp = client.get(f"/api/report/{doc_id}?regenerate=false")
    assert resp.status_code == 404
    assert "missing or corrupted" in resp.json()["detail"].lower()


def test_download_report_returns_404_when_file_zero_bytes(api_client):
    """When a report file is truncated to 0 bytes and regenerate=False, download must return 404."""
    client, test_settings = api_client
    nda_file = Path("data/sample_contracts/sample_nda.pdf")
    with nda_file.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    client.post(f"/api/analyze/{doc_id}")

    # Truncate report to 0 bytes
    rep_path = test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf"
    rep_path.write_bytes(b"")

    resp = client.get(f"/api/report/{doc_id}?regenerate=false")
    assert resp.status_code == 404
    assert "missing or corrupted" in resp.json()["detail"].lower()


def test_report_listing_flags_missing_files(api_client):
    """Reports endpoint must correctly indicate report_exists=False when the PDF is removed from disk."""
    client, test_settings = api_client
    nda_file = Path("data/sample_contracts/sample_nda.pdf")
    with nda_file.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    client.post(f"/api/analyze/{doc_id}")

    # Remove the file from disk
    rep_path = test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf"
    if rep_path.exists():
        rep_path.unlink()

    resp = client.get("/api/reports")
    assert resp.status_code == 200
    matched = [r for r in resp.json() if r["document_id"] == doc_id]
    assert len(matched) == 1
    assert matched[0]["report_exists"] is False
    assert matched[0]["file_ok"] is False


def test_report_regeneration_with_malformed_missing_clauses_json(api_client):
    """Report regeneration must gracefully handle malformed JSON in missing_clauses_json."""
    client, test_settings = api_client
    from backend.database import Document, get_db

    nda_file = Path("data/sample_contracts/sample_nda.pdf")
    with nda_file.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    client.post(f"/api/analyze/{doc_id}")

    # Delete report from disk so regeneration is triggered
    rep_path = test_settings.reports_dir / f"LegalEase_Report_{doc_id}.pdf"
    if rep_path.exists():
        rep_path.unlink()

    # Intentionally corrupt missing_clauses_json in DB
    db_gen = client.app.dependency_overrides.get(get_db, get_db)()
    db = next(db_gen)
    try:
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        doc.missing_clauses_json = "{invalid_json_corrupt"
        db.commit()
    finally:
        db.close()

    # Request report download (triggers regeneration)
    resp = client.get(f"/api/report/{doc_id}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")


def test_malformed_analysis_data_does_not_crash_pdf_generation(tmp_path: Path):
    """Direct generate_analysis_pdf call with None and empty inputs must not raise unhandled exceptions."""
    from backend.services.pdf_service import generate_analysis_pdf

    out_file = tmp_path / "robustness_test.pdf"
    res = generate_analysis_pdf(
        output_path=out_file,
        document_meta={"document_id": "TEST-ROBUST", "filename": "test.pdf"},
        overview=None,
        executive_summary=None,
        clauses=None,
        risk_results=None,
        comparisons=[{"clause_id": "CL-01", "differences": "{corrupt_diff_str"}],
        missing_clauses=None,
    )
    assert res.exists()
    assert res.stat().st_size > 0
