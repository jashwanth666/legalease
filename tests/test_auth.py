"""Unit and integration tests for Authentication, Argon2id hashing, and JWT tokens."""

from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.auth import reset_auth_rate_limits
from backend.auth.security import (
    JWTError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app


class _AuthTestSettings(Settings):
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
def auth_client(tmp_path: Path):
    reset_auth_rate_limits()
    db_path = tmp_path / "auth_test.db"
    settings = _AuthTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
        jwt_secret_key="test-secret-key-for-unit-testing-32bytes!",
        admin_bootstrap_secret="test-bootstrap-secret-1234567890",
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


def test_argon2_password_hashing():
    """Verify modern Argon2id password hashing and constant-time verification."""
    password = "CorrectHorseBatteryStaple123!"
    hashed = hash_password(password)

    assert hashed.startswith("$argon2id$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(password, "") is False

    # Short password must raise ValueError
    with pytest.raises(ValueError):
        hash_password("short")


def test_jwt_create_and_decode():
    """Verify RFC 7519 HMAC-SHA256 JWT access token issuance, claims, and validation."""
    secret = "my-secret-key-32-bytes-long-super-safe"
    data = {"sub": "alice@company.com", "role": "admin", "tenant_id": "tenant_acme"}

    token = create_access_token(data=data, secret_key=secret, expires_delta=timedelta(minutes=30))
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    decoded = decode_access_token(token, secret_key=secret)
    assert decoded["sub"] == "alice@company.com"
    assert decoded["role"] == "admin"
    assert decoded["tenant_id"] == "tenant_acme"
    assert "exp" in decoded
    assert "iat" in decoded

    # Tampered signature must fail
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.tamperedsig"
    with pytest.raises(JWTError, match="Invalid JWT token signature"):
        decode_access_token(tampered, secret_key=secret)

    # Wrong secret key must fail
    with pytest.raises(JWTError, match="Invalid JWT token signature"):
        decode_access_token(token, secret_key="wrong-secret-key-32-bytes-long!")

    # Expired token must fail
    expired_token = create_access_token(data=data, secret_key=secret, expires_delta=timedelta(seconds=-10))
    with pytest.raises(JWTError, match="JWT token has expired"):
        decode_access_token(expired_token, secret_key=secret)


def test_register_and_login_flow(auth_client):
    """End-to-end test of administrator bootstrap, user registration, login, and access controls."""
    client, settings = auth_client

    # 1. Check bootstrap status initially
    status_resp = client.get("/api/auth/bootstrap-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["bootstrapped"] is False

    # 2. Administrator bootstrap initializes the first system administrator
    admin_payload = {
        "email": "bootstrap_admin@legalcorp.com",
        "password": "SecurePassword123!",
        "full_name": "Elena Rostova",
        "bootstrap_secret": "test-bootstrap-secret-1234567890",
        "tenant_id": "tenant_legalcorp",
    }
    boot_resp = client.post("/api/auth/bootstrap-admin", json=admin_payload)
    assert boot_resp.status_code == 201
    admin_data = boot_resp.json()
    assert admin_data["email"] == "bootstrap_admin@legalcorp.com"
    assert admin_data["role"] == "admin"
    assert admin_data["tenant_id"] == "tenant_legalcorp"
    assert "hashed_password" not in admin_data

    # Bootstrap status now reflects that setup is completed
    status_resp2 = client.get("/api/auth/bootstrap-status")
    assert status_resp2.status_code == 200
    assert status_resp2.json()["bootstrapped"] is True

    # 3. Duplicate bootstrap attempt is permanently rejected (HTTP 409)
    dup_boot = client.post("/api/auth/bootstrap-admin", json=admin_payload)
    assert dup_boot.status_code == 409
    assert "already been initialized" in dup_boot.json()["detail"]

    # 4. Public registration strictly creates role 'employee' in an isolated workspace
    emp_payload = {
        "email": "worker@acme.com",
        "password": "WorkerPassword123!",
        "full_name": "Bob Worker",
        "tenant_id": "tenant_acme",
    }
    emp_resp = client.post("/api/auth/register", json=emp_payload)
    assert emp_resp.status_code == 201
    assert emp_resp.json()["role"] == "employee"
    assert emp_resp.json()["tenant_id"] == "tenant_acme"

    # Duplicate email in public registration rejected (HTTP 409)
    dup_emp = client.post("/api/auth/register", json=emp_payload)
    assert dup_emp.status_code == 409
    assert "already exists" in dup_emp.json()["detail"]

    # 5. Attempting to register with privileged role 'admin' or 'legal_reviewer' via public API is rejected (HTTP 422)
    priv_payload = {
        "email": "hacker@evil.com",
        "password": "HackerPassword123!",
        "full_name": "Evil Actor",
        "role": "admin",
    }
    priv_resp = client.post("/api/auth/register", json=priv_payload)
    assert priv_resp.status_code == 422
    assert "Public self-registration only permits creating Employee accounts" in priv_resp.text

    # 6. Attempting to self-register into an EXISTING tenant organization is rejected (HTTP 403)
    infiltrate_payload = {
        "email": "intruder@evil.com",
        "password": "IntruderPassword123!",
        "full_name": "Tenant Infiltrator",
        "tenant_id": "tenant_legalcorp",  # already exists!
    }
    infiltrate_resp = client.post("/api/auth/register", json=infiltrate_payload)
    assert infiltrate_resp.status_code == 403
    assert "already exists" in infiltrate_resp.json()["detail"]

    # 7. Admin creates a legal_reviewer within their tenant via POST /api/auth/users
    admin_login = client.post(
        "/api/auth/login",
        json={"email": "bootstrap_admin@legalcorp.com", "password": "SecurePassword123!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create_user_resp = client.post(
        "/api/auth/users",
        json={
            "email": "counsel@legalcorp.com",
            "password": "CounselPassword123!",
            "full_name": "Counsel User",
            "role": "legal_reviewer",
        },
        headers=admin_headers,
    )
    assert create_user_resp.status_code == 201
    counsel_id = create_user_resp.json()["id"]
    assert create_user_resp.json()["role"] == "legal_reviewer"
    assert create_user_resp.json()["tenant_id"] == "tenant_legalcorp"

    # 8. Non-admin cannot create users via /api/auth/users (HTTP 403)
    worker_login = client.post(
        "/api/auth/login",
        json={"email": "worker@acme.com", "password": "WorkerPassword123!"},
    )
    worker_token = worker_login.json()["access_token"]
    forbidden_resp = client.post(
        "/api/auth/users",
        json={
            "email": "illegal@acme.com",
            "password": "Password123!",
            "role": "admin",
        },
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert forbidden_resp.status_code == 403

    # 9. Admin updates user status via PATCH /api/auth/users/{user_id}
    deact_resp = client.patch(
        f"/api/auth/users/{counsel_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert deact_resp.status_code == 200
    assert deact_resp.json()["is_active"] is False

    # Deactivated user cannot login (HTTP 403)
    deact_login = client.post(
        "/api/auth/login",
        json={"email": "counsel@legalcorp.com", "password": "CounselPassword123!"},
    )
    assert deact_login.status_code == 403
    assert "deactivated" in deact_login.json()["detail"].lower()

    # 10. Admin cannot deactivate the last active administrator of the tenant (HTTP 400)
    admin_id = admin_data["id"]
    deact_admin_resp = client.patch(
        f"/api/auth/users/{admin_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert deact_admin_resp.status_code == 400
    assert "last active administrator" in deact_admin_resp.json()["detail"].lower()

    # 11. Authenticated /me endpoint
    me_resp = client.get("/api/auth/me", headers=admin_headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "bootstrap_admin@legalcorp.com"
    assert me_data["role"] == "admin"
    assert me_data["tenant_id"] == "tenant_legalcorp"

    # 12. Logout endpoint
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "ok"

    # 13. Unauthenticated /me endpoint rejected
    client.cookies.clear()
    unauth_resp = client.get("/api/auth/me")
    assert unauth_resp.status_code == 401


def test_production_jwt_secret_validation():
    """Verify that in production environment, default or weak JWT secret raises ValueError on validation."""
    prod_settings_bad = Settings(
        environment="production",
        jwt_secret_key="insecure-default-secret-key-change-in-production",
    )
    with pytest.raises(ValueError, match="CRITICAL SECURITY CONFIGURATION ERROR"):
        prod_settings_bad.validate_production_security()

    prod_settings_good = Settings(
        environment="production",
        jwt_secret_key="a-very-long-and-secure-randomly-generated-secret-key-32bytes",
    )
    # Good settings must not raise
    prod_settings_good.validate_production_security()
