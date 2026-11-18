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


def test_atomic_concurrency_cas_claiming(job_env):
    """Under simultaneous parallel requests, atomic CAS lock ensures exactly one claims the job (202) and others get 409."""
    import concurrent.futures

    client, _ = job_env
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"

    with sample_pdf.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("concurrent_cas.pdf", f, "application/pdf")})
    assert up.status_code == 201
    doc_id = up.json()["document_id"]

    def trigger_analyze():
        return client.post(f"/api/analyze/{doc_id}")

    # Fire 5 parallel analysis requests simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(trigger_analyze) for _ in range(5)]
        results = [f.result() for f in futures]

    statuses = [r.status_code for r in results]
    # Exactly one request must succeed with 202 Accepted, and remaining 4 must be 409 Conflict
    assert statuses.count(202) == 1
    assert statuses.count(409) == 4


def test_stale_job_recovery_on_startup(tmp_path: Path):
    """Lifespan startup must detect and recover jobs left in queued/processing state from a prior crashed server."""
    db_path = tmp_path / "recovery_test.db"
    settings = _JobTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
    )
    settings.ensure_directories()
    db_module.configure_database(settings.database_url)

    # Insert a stale document directly into the database as if server crashed while processing
    with db_module.SessionLocal() as db:
        stale_doc = Document(
            document_id="stale-crashed-doc-123",
            filename="crashed.pdf",
            stored_filename="crashed.pdf",
            file_type="pdf",
            file_size=1024,
            tenant_id="default_tenant",
            processing_status="processing",
            current_stage="risk_assessment",
        )
        db.add(stale_doc)
        db.commit()

    # Now launch the app, triggering the lifespan context manager
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as test_client:
        # Check that the stale job was detected and recovered
        with db_module.SessionLocal() as db:
            recovered_doc = db.query(Document).filter(Document.document_id == "stale-crashed-doc-123").first()
            assert recovered_doc.processing_status == "failed"
            assert recovered_doc.current_stage == "interrupted"
            assert "interrupted by server restart" in recovered_doc.last_error.lower()

    app.dependency_overrides.clear()
