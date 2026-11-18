"""Security and multi-tenant isolation tests for LegalEase.

Verifies:
1. Strict 401 Unauthorized on unauthenticated requests.
2. Complete cross-tenant document isolation (IDOR defense - 404 on foreign tenant documents).
3. Role-based access control (Admin, Legal Reviewer, Employee).
4. Employee cannot delete documents owned by other users (403 Forbidden).
5. Only Admin can trigger reference template index rebuilds.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.auth.security import create_access_token, hash_password
from backend.config import Settings, get_settings
from backend.database import User
from backend.database import db as db_module
from backend.main import create_app


class _IsolationTestSettings(Settings):
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
def isolation_env(tmp_path: Path):
    db_path = tmp_path / "isolation_test.db"
    settings = _IsolationTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
    )
    settings.ensure_directories()
    db_module.configure_database(settings.database_url)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    # Pre-seed users across tenants and roles
    db = db_module.SessionLocal()
    try:
        user_a = User(
            email="admin_a@tenant-a.com",
            hashed_password=hash_password("PasswordA123!"),
            full_name="Admin Tenant A",
            role="admin",
            tenant_id="tenant_alpha",
            is_active=True,
        )
        emp_a = User(
            email="emp_a@tenant-a.com",
            hashed_password=hash_password("PasswordA123!"),
            full_name="Employee Tenant A",
            role="employee",
            tenant_id="tenant_alpha",
            is_active=True,
        )
        emp_a2 = User(
            email="emp_a2@tenant-a.com",
            hashed_password=hash_password("PasswordA123!"),
            full_name="Employee 2 Tenant A",
            role="employee",
            tenant_id="tenant_alpha",
            is_active=True,
        )
        user_b = User(
            email="admin_b@tenant-b.com",
            hashed_password=hash_password("PasswordB123!"),
            full_name="Admin Tenant B",
            role="admin",
            tenant_id="tenant_beta",
            is_active=True,
        )
        db.add_all([user_a, emp_a, emp_a2, user_b])
        db.commit()
    finally:
        db.close()

    tokens = {
        "admin_a": create_access_token({"sub": "admin_a@tenant-a.com", "tenant_id": "tenant_alpha", "role": "admin"}, secret_key=settings.jwt_secret_key),
        "emp_a": create_access_token({"sub": "emp_a@tenant-a.com", "tenant_id": "tenant_alpha", "role": "employee"}, secret_key=settings.jwt_secret_key),
        "emp_a2": create_access_token({"sub": "emp_a2@tenant-a.com", "tenant_id": "tenant_alpha", "role": "employee"}, secret_key=settings.jwt_secret_key),
        "admin_b": create_access_token({"sub": "admin_b@tenant-b.com", "tenant_id": "tenant_beta", "role": "admin"}, secret_key=settings.jwt_secret_key),
    }

    with TestClient(app) as client:
        yield client, tokens, settings

    app.dependency_overrides.clear()


def test_unauthenticated_requests_rejected(isolation_env):
    """All protected document endpoints must return 401 when no token is provided."""
    client, _, _ = isolation_env
    # Clear any residual headers/cookies
    client.headers.clear()
    client.cookies.clear()

    endpoints = [
        ("GET", "/api/documents"),
        ("GET", "/api/documents/DOC-FAKE123"),
        ("DELETE", "/api/documents/DOC-FAKE123"),
        ("POST", "/api/analyze/DOC-FAKE123"),
        ("GET", "/api/status/DOC-FAKE123"),
        ("GET", "/api/analysis/DOC-FAKE123"),
        ("GET", "/api/clauses/DOC-FAKE123"),
        ("GET", "/api/metadata/DOC-FAKE123"),
        ("GET", "/api/compare/DOC-FAKE123"),
        ("GET", "/api/reports"),
        ("GET", "/api/report/DOC-FAKE123"),
        ("POST", "/api/templates/rebuild"),
    ]

    for method, path in endpoints:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"
        assert "Authentication required" in resp.json()["detail"] or "Invalid" in resp.json()["detail"]


def test_cross_tenant_document_isolation(isolation_env):
    """Tenant B must never see, access, analyze, or delete documents uploaded by Tenant A."""
    client, tokens, _ = isolation_env
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"

    # 1. Tenant A uploads a document
    with sample_pdf.open("rb") as f:
        up_resp = client.post(
            "/api/upload",
            files={"file": ("tenant_a_contract.pdf", f, "application/pdf")},
            headers={"Authorization": f"Bearer {tokens['admin_a']}"},
        )
    assert up_resp.status_code == 201
    doc_id_a = up_resp.json()["document_id"]

    # 2. Tenant A can see it in list and get details
    list_a = client.get("/api/documents", headers={"Authorization": f"Bearer {tokens['admin_a']}"})
    assert list_a.status_code == 200
    assert any(d["document_id"] == doc_id_a for d in list_a.json())

    # 3. Tenant B lists documents -> doc_id_a MUST NOT be in list
    list_b = client.get("/api/documents", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert list_b.status_code == 200
    assert not any(d["document_id"] == doc_id_a for d in list_b.json())

    # 4. Tenant B tries to retrieve doc_id_a -> 404 Not Found (no IDOR enumeration)
    get_b = client.get(f"/api/documents/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert get_b.status_code == 404
    assert f"Document '{doc_id_a}' not found" in get_b.json()["detail"]

    # 5. Tenant B tries to analyze doc_id_a -> 404 Not Found
    analyze_b = client.post(f"/api/analyze/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert analyze_b.status_code == 404

    # 6. Tenant B tries to query status -> 404 Not Found
    status_b = client.get(f"/api/status/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert status_b.status_code == 404

    # 7. Tenant B tries to query analysis, clauses, metadata, compare, and report download -> 404 Not Found
    for subpath in ("analysis", "clauses", "metadata", "compare", "report"):
        cross_resp = client.get(f"/api/{subpath}/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
        assert cross_resp.status_code == 404, f"/api/{subpath}/{doc_id_a} returned {cross_resp.status_code}, expected 404"

    # 8. Tenant B tries to delete doc_id_a -> 404 Not Found
    del_b = client.delete(f"/api/documents/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert del_b.status_code == 404

    # 9. Tenant B cannot see Tenant A's users via /api/auth/users
    users_b_resp = client.get("/api/auth/users", headers={"Authorization": f"Bearer {tokens['admin_b']}"})
    assert users_b_resp.status_code == 200
    b_emails = {u["email"] for u in users_b_resp.json()}
    assert "admin_b@tenant-b.com" in b_emails
    assert "admin_a@tenant-a.com" not in b_emails
    assert "emp_a@tenant-a.com" not in b_emails

    # 10. Fabricated document ID checks for both tenants -> 404 Not Found
    for fake_id in ("DOC-FABRICATED999", "DOC-NONEXISTENT"):
        assert client.get(f"/api/documents/{fake_id}", headers={"Authorization": f"Bearer {tokens['admin_a']}"}).status_code == 404
        assert client.get(f"/api/documents/{fake_id}", headers={"Authorization": f"Bearer {tokens['admin_b']}"}).status_code == 404
        assert client.get(f"/api/analysis/{fake_id}", headers={"Authorization": f"Bearer {tokens['admin_a']}"}).status_code == 404
        assert client.delete(f"/api/documents/{fake_id}", headers={"Authorization": f"Bearer {tokens['admin_a']}"}).status_code == 404

    # Document still exists for Tenant A
    get_a = client.get(f"/api/documents/{doc_id_a}", headers={"Authorization": f"Bearer {tokens['admin_a']}"})
    assert get_a.status_code == 200


def test_role_based_permissions(isolation_env):
    """Verify role checks: employees can only delete their own docs; template rebuild requires admin."""
    client, tokens, _ = isolation_env
    sample_pdf = Path(__file__).resolve().parent.parent / "data" / "sample_contracts" / "sample_nda.pdf"

    # Employee A uploads a document
    with sample_pdf.open("rb") as f:
        up_resp = client.post(
            "/api/upload",
            files={"file": ("emp_contract.pdf", f, "application/pdf")},
            headers={"Authorization": f"Bearer {tokens['emp_a']}"},
        )
    assert up_resp.status_code == 201
    doc_id = up_resp.json()["document_id"]

    # Another employee in same tenant tries to delete Employee A's document -> 403 Forbidden
    del_other = client.delete(
        f"/api/documents/{doc_id}",
        headers={"Authorization": f"Bearer {tokens['emp_a2']}"},
    )
    assert del_other.status_code == 403
    assert "permission to delete" in del_other.json()["detail"].lower()

    # Employee tries to rebuild reference templates vector index -> 403 Forbidden
    rebuild_emp = client.post(
        "/api/templates/rebuild",
        headers={"Authorization": f"Bearer {tokens['emp_a']}"},
    )
    assert rebuild_emp.status_code == 403
    assert "Required roles: admin" in rebuild_emp.json()["detail"]

    # Admin in same tenant CAN rebuild reference templates -> 200 OK
    rebuild_admin = client.post(
        "/api/templates/rebuild",
        headers={"Authorization": f"Bearer {tokens['admin_a']}"},
    )
    assert rebuild_admin.status_code == 200
    assert rebuild_admin.json()["status"] == "ok"

    # Admin in same tenant CAN delete Employee A's document -> 200 OK
    del_admin = client.delete(
        f"/api/documents/{doc_id}",
        headers={"Authorization": f"Bearer {tokens['admin_a']}"},
    )
    assert del_admin.status_code == 200
    assert del_admin.json()["deleted"] is True
