"""Tests for document upload, validation, storage, listing, and deletion."""

import io
from pathlib import Path
import zipfile

import docx
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.guardrails.document_guard import DocumentValidationError, resolve_contained_path
from backend.main import create_app
from tests.conftest import create_test_user


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


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test_legalease.db"
    test_settings = _TestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        max_upload_size_mb=1,
    )
    test_settings.ensure_directories()
    configure_database(test_settings.database_url)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings

    _, token = create_test_user(secret_key=test_settings.jwt_secret_key)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client, test_settings

    app.dependency_overrides.clear()


def _create_sample_docx_bytes() -> bytes:
    doc = docx.Document()
    doc.add_heading("1. Definitions", level=1)
    doc.add_paragraph("Client agrees to pay fees within 30 days of invoice.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Milestone"
    table.cell(0, 1).text = "Fee"
    table.cell(1, 0).text = "Delivery"
    table.cell(1, 1).text = "$5,000"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _create_encrypted_pdf_bytes() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Confidential protected contract text.")
    encrypted = pdf.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner123",
        user_pw="user123",
    )
    pdf.close()
    return encrypted


def test_health_endpoint(client):
    test_client, _ = client
    resp = test_client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "LegalEase"
    assert "disclaimer" in payload


def test_upload_pdf_and_retrieve_and_delete(client):
    test_client, test_settings = client
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"
    assert sample_pdf.exists()

    with sample_pdf.open("rb") as f:
        resp = test_client.post(
            "/api/upload",
            files={"file": ("sample_nda.pdf", f, "application/pdf")},
        )

    assert resp.status_code == 201
    data = resp.json()
    doc_id = data["document_id"]
    assert doc_id.startswith("DOC-")
    assert data["file_type"] == "pdf"
    assert data["processing_status"] == "uploaded"
    assert data["page_count"] == 2
    assert data["ocr_required"] is False

    assert (test_settings.upload_dir / f"{doc_id}.pdf").exists()
    assert (test_settings.extracted_dir / f"{doc_id}.json").exists()

    list_resp = test_client.get("/api/documents")
    assert list_resp.status_code == 200
    assert any(item["document_id"] == doc_id for item in list_resp.json())

    detail_resp = test_client.get(f"/api/documents/{doc_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["document"]["document_id"] == doc_id
    assert len(detail["extracted"]["pages"]) == 2
    assert detail["extracted"]["pages"][0]["page_number"] == 1
    assert detail["extracted"]["pages"][1]["page_number"] == 2

    del_resp = test_client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    assert not (test_settings.upload_dir / f"{doc_id}.pdf").exists()
    assert not (test_settings.extracted_dir / f"{doc_id}.json").exists()

    missing_resp = test_client.get(f"/api/documents/{doc_id}")
    assert missing_resp.status_code == 404


def test_upload_docx_success(client):
    test_client, _ = client
    docx_bytes = _create_sample_docx_bytes()
    resp = test_client.post(
        "/api/upload",
        files={
            "file": (
                "service.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["file_type"] == "docx"
    assert payload["ocr_required"] is False

    detail = test_client.get(f"/api/documents/{payload['document_id']}").json()
    assert detail["extracted"]["location_mode"] == "docx_paragraph"
    assert detail["extracted"]["pages"][0]["page_number"] is None
    text = detail["extracted"]["pages"][0]["text"]
    assert "Client agrees to pay fees within 30 days of invoice." in text
    assert "Milestone | Fee" in text


def test_reject_invalid_extension(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/upload",
        files={"file": ("notes.txt", b"hello contract", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_reject_empty_file(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_reject_spoofed_pdf_content(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/upload",
        files={"file": ("fake.pdf", b"not a real pdf binary", "application/pdf")},
    )
    assert resp.status_code == 400


def test_reject_corrupted_docx(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/upload",
        files={
            "file": (
                "broken.docx",
                b"PK\x03\x04corruptedzipbytes",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 400


def test_reject_encrypted_pdf(client):
    test_client, _ = client
    encrypted_bytes = _create_encrypted_pdf_bytes()
    resp = test_client.post(
        "/api/upload",
        files={"file": ("locked.pdf", encrypted_bytes, "application/pdf")},
    )
    assert resp.status_code == 400
    assert "Encrypted" in resp.json()["detail"]


def test_reject_oversized_upload(client):
    test_client, _ = client
    oversized = b"%PDF-1.4\n" + (b"0" * (1024 * 1024 + 50))
    resp = test_client.post(
        "/api/upload",
        files={"file": ("huge.pdf", oversized, "application/pdf")},
    )
    assert resp.status_code == 413


def test_reject_docx_zip_traversal_and_path_containment(client, tmp_path: Path):
    test_client, _ = client
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", b"escape")
        zf.writestr("word/document.xml", b"<document/>")

    resp = test_client.post(
        "/api/upload",
        files={
            "file": (
                "traversal.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 400
    assert "Invalid DOCX archive entry" in resp.json()["detail"]

    base = tmp_path / "managed"
    base.mkdir()
    outside = tmp_path / "outside.pdf"
    with pytest.raises(DocumentValidationError):
        resolve_contained_path(base, outside)
