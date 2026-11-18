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
    """End-to-end test of user registration, login, and authenticated /me endpoint."""
    client, settings = auth_client

    # 1. Register new user
    reg_payload = {
        "email": "reviewer@legalcorp.com",
        "password": "SecurePassword123!",
        "full_name": "Elena Rostova",
        "role": "legal_reviewer",
        "tenant_id": "tenant_legalcorp",
    }
    reg_resp = client.post("/api/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["email"] == "reviewer@legalcorp.com"
    assert user_data["role"] == "legal_reviewer"
    assert user_data["tenant_id"] == "tenant_legalcorp"
    assert "hashed_password" not in user_data  # Sensitive hash must never be exposed!

    # 2. Duplicate registration rejection
    dup_resp = client.post("/api/auth/register", json=reg_payload)
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]

    # 3. Login with incorrect password
    bad_login = client.post(
        "/api/auth/login",
        json={"email": "reviewer@legalcorp.com", "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    # 4. Login with correct password
    good_login = client.post(
        "/api/auth/login",
        json={"email": "reviewer@legalcorp.com", "password": "SecurePassword123!"},
    )
    assert good_login.status_code == 200
    token_data = good_login.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    token = token_data["access_token"]

    # 5. Authenticated /me endpoint
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "reviewer@legalcorp.com"
    assert me_data["role"] == "legal_reviewer"
    assert me_data["tenant_id"] == "tenant_legalcorp"

    # 6. Unauthenticated /me endpoint rejected
    client.cookies.clear()
    unauth_resp = client.get("/api/auth/me")
    assert unauth_resp.status_code == 401
