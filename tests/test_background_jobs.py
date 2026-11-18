"""Background job concurrency, state transitions, and real-time stage progress tests."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.database import Document
from backend.database import db as db_module
from backend.graph.nodes import ALL_WORKFLOW_STAGES, STAGE_PROGRESS
from backend.main import create_app
from tests.conftest import create_test_user


class _JobTestSettings(Settings):
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
def job_env(tmp_path: Path):
    db_path = tmp_path / "job_test.db"
    settings = _JobTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
    )
    settings.ensure_directories()
    db_module.configure_database(settings.database_url)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    _, token = create_test_user(secret_key=settings.jwt_secret_key)

    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, settings

    app.dependency_overrides.clear()


def test_duplicate_analysis_prevented_with_409_conflict(job_env):
    """When a document is already queued or processing, subsequent analyze requests must return 409 Conflict."""
    client, _ = job_env
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"

    with sample_pdf.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("test_conflict.pdf", f, "application/pdf")})
    assert up.status_code == 201
    doc_id = up.json()["document_id"]

    # 1. First trigger queues the document
    resp1 = client.post(f"/api/analyze/{doc_id}")
    assert resp1.status_code == 202
    assert resp1.json()["processing_status"] == "queued"

    # Set state in DB directly to simulate active 'processing'
    db = db_module.SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        doc.processing_status = "processing"
        doc.current_stage = "risk_assessment"
        db.commit()
    finally:
        db.close()

    # 2. Duplicate trigger while processing -> MUST reject with 409 Conflict
    resp2 = client.post(f"/api/analyze/{doc_id}")
    assert resp2.status_code == 409
    assert "already being analyzed" in resp2.json()["detail"]

    # 3. Duplicate trigger while queued -> MUST also reject with 409 Conflict
    db = db_module.SessionLocal()
    try:
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        doc.processing_status = "queued"
        doc.current_stage = "queued"
        db.commit()
    finally:
        db.close()

    resp3 = client.post(f"/api/analyze/{doc_id}")
    assert resp3.status_code == 409
    assert "already being analyzed" in resp3.json()["detail"]


def test_real_time_workflow_stage_tracking(job_env):
    """Verify that document analysis tracks all 12 stages, updates completion percentage, and reports pending stages."""
    client, _ = job_env
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"

    with sample_pdf.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("test_stages.pdf", f, "application/pdf")})
    assert up.status_code == 201
    doc_id = up.json()["document_id"]

    # Initial status
    initial_status = client.get(f"/api/status/{doc_id}").json()
    assert initial_status["processing_status"] == "uploaded"
    assert initial_status["progress_percent"] == 0
    assert initial_status["completed_stages"] == []
    assert len(initial_status["pending_stages"]) == len(ALL_WORKFLOW_STAGES)

    # Run analysis to completion
    an_resp = client.post(f"/api/analyze/{doc_id}?wait=true")
    assert an_resp.status_code == 200

    # Final status after completion
    final_status = client.get(f"/api/status/{doc_id}").json()
    assert final_status["processing_status"] == "analyzed"
    assert final_status["current_stage"] == "completed"
    assert final_status["progress_percent"] == 100
    assert final_status["pending_stages"] == []
    assert final_status["report_available"] is True

    # Verify that workflow stages were recorded in completed_stages
    completed = final_status["completed_stages"]
    assert "document_validation" in completed
    assert "text_extraction" in completed
    assert "clause_splitting" in completed
    assert "clause_classification" in completed
    assert "risk_assessment" in completed
    assert "template_comparison" in completed
    assert "missing_clause_detection" in completed
    assert "metadata_extraction" in completed
    assert "evidence_verification" in completed
    assert "summary_generation" in completed
    assert "pdf_generation" in completed
