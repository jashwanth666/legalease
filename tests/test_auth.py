"""Unit and integration tests for Authentication, Argon2id hashing, and JWT tokens."""

from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

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
    db_path = tmp_path / "auth_test.db"
    settings = _AuthTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
        jwt_secret_key="test-secret-key-for-unit-testing-32bytes!",
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
    """End-to-end test of user registration, bootstrap admin, login, and authenticated /me endpoint."""
    client, settings = auth_client

    # 1. First registered user in empty DB is bootstrapped as system admin
    admin_payload = {
        "email": "bootstrap_admin@legalcorp.com",
        "password": "SecurePassword123!",
        "full_name": "Elena Rostova",
        "tenant_id": "tenant_legalcorp",
    }
    reg_resp = client.post("/api/auth/register", json=admin_payload)
    assert reg_resp.status_code == 201
    admin_data = reg_resp.json()
    assert admin_data["email"] == "bootstrap_admin@legalcorp.com"
    assert admin_data["role"] == "admin"
    assert admin_data["tenant_id"] == "tenant_legalcorp"
    assert "hashed_password" not in admin_data

    # 2. Duplicate registration rejection
    dup_resp = client.post("/api/auth/register", json=admin_payload)
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]

    # 3. Subsequent public registration can ONLY create role 'employee'
    emp_payload = {
        "email": "worker@acme.com",
        "password": "WorkerPassword123!",
        "full_name": "Bob Worker",
        "tenant_id": "tenant_acme",
    }
    emp_resp = client.post("/api/auth/register", json=emp_payload)
    assert emp_resp.status_code == 201
    assert emp_resp.json()["role"] == "employee"

    # 4. Attempting to register with privileged role 'admin' or 'legal_reviewer' via public API is rejected
    priv_payload = {
        "email": "hacker@evil.com",
        "password": "HackerPassword123!",
        "full_name": "Evil Actor",
        "role": "admin",
    }
    priv_resp = client.post("/api/auth/register", json=priv_payload)
    assert priv_resp.status_code == 422
    assert "Public self-registration only permits creating Employee accounts" in priv_resp.text

    # 5. Attempting to self-register into an EXISTING tenant organization is rejected (HTTP 403)
    infiltrate_payload = {
        "email": "intruder@evil.com",
        "password": "IntruderPassword123!",
        "full_name": "Tenant Infiltrator",
        "tenant_id": "tenant_legalcorp",  # already exists!
    }
    infiltrate_resp = client.post("/api/auth/register", json=infiltrate_payload)
    assert infiltrate_resp.status_code == 403
    assert "already exists" in infiltrate_resp.json()["detail"]

    # 6. Admin creates a legal_reviewer within their tenant via POST /api/auth/users
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
    assert create_user_resp.json()["role"] == "legal_reviewer"
    assert create_user_resp.json()["tenant_id"] == "tenant_legalcorp"

    # 7. Non-admin cannot create users via /api/auth/users (HTTP 403)
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

    # 8. Authenticated /me endpoint
    me_resp = client.get("/api/auth/me", headers=admin_headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "bootstrap_admin@legalcorp.com"
    assert me_data["role"] == "admin"
    assert me_data["tenant_id"] == "tenant_legalcorp"

    # 9. Unauthenticated /me endpoint rejected
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
