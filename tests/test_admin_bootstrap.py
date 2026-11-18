"""Unit and integration tests for secure, one-time administrator bootstrap.

Verifies:
1. First administrator can be initialized using a valid bootstrap secret.
2. Invalid bootstrap secret is rejected with HTTP 401.
3. Missing/unconfigured bootstrap secret on server is rejected with HTTP 403.
4. Second bootstrap attempt is rejected with HTTP 409.
5. Concurrent bootstrap requests cannot create multiple initial administrators (atomic lock).
6. Public self-registration cannot create an administrator, even when the database is empty.
7. Application restart does not reset administrator initialization state.
8. Bootstrap secret is never exposed in API responses.
9. Validation rules (email format and minimum password length).
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.auth import reset_auth_rate_limits
from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app


class _BootstrapTestSettings(Settings):
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
def bootstrap_env(tmp_path: Path):
    reset_auth_rate_limits()
    db_path = tmp_path / "bootstrap_test.db"
    settings = _BootstrapTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
        jwt_secret_key="test-secret-key-for-bootstrap-testing-32bytes!",
        admin_bootstrap_secret="correct-bootstrap-secret-phrase-456",
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


def test_public_registration_never_creates_admin_in_empty_db(bootstrap_env):
    """In an empty database, public self-registration must ONLY create an employee account, NEVER an admin."""
    client, _ = bootstrap_env

    status_resp = client.get("/api/auth/bootstrap-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["bootstrapped"] is False

    reg_payload = {
        "email": "first_user@company.com",
        "password": "Password123!",
        "full_name": "First User",
    }
    resp = client.post("/api/auth/register", json=reg_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "employee"
    assert data["email"] == "first_user@company.com"

    # Bootstrap status remains False because no administrator has been initialized yet
    status_resp2 = client.get("/api/auth/bootstrap-status")
    assert status_resp2.status_code == 200
    assert status_resp2.json()["bootstrapped"] is False


def test_bootstrap_admin_with_valid_secret(bootstrap_env):
    """First administrator is successfully provisioned using the valid bootstrap secret."""
    client, settings = bootstrap_env

    payload = {
        "email": "chief_admin@enterprise.com",
        "password": "AdminPassword123!",
        "full_name": "Chief Administrator",
        "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
        "tenant_id": "tenant_enterprise",
    }
    resp = client.post("/api/auth/bootstrap-admin", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "chief_admin@enterprise.com"
    assert data["role"] == "admin"
    assert data["tenant_id"] == "tenant_enterprise"
    assert "bootstrap_secret" not in data
    assert "hashed_password" not in data

    # Check status
    status_resp = client.get("/api/auth/bootstrap-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["bootstrapped"] is True


def test_bootstrap_admin_invalid_secret_rejected(bootstrap_env):
    """Providing an invalid bootstrap secret must return HTTP 401 Unauthorized."""
    client, _ = bootstrap_env

    payload = {
        "email": "intruder@enterprise.com",
        "password": "Password123!",
        "bootstrap_secret": "wrong-secret-guess",
    }
    resp = client.post("/api/auth/bootstrap-admin", json=payload)
    assert resp.status_code == 401
    assert "Invalid administrator bootstrap secret" in resp.json()["detail"]


def test_bootstrap_admin_unconfigured_secret_rejected(tmp_path: Path):
    """When ADMIN_BOOTSTRAP_SECRET is not configured on the server, bootstrap is disabled (HTTP 403)."""
    db_path = tmp_path / "no_secret.db"
    settings = _BootstrapTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
        jwt_secret_key="test-secret-key-for-bootstrap-testing-32bytes!",
        admin_bootstrap_secret="",  # Unconfigured!
    )
    settings.ensure_directories()
    configure_database(settings.database_url)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        payload = {
            "email": "admin@enterprise.com",
            "password": "Password123!",
            "bootstrap_secret": "any-secret",
        }
        resp = client.post("/api/auth/bootstrap-admin", json=payload)
        assert resp.status_code == 403
        assert "disabled or ADMIN_BOOTSTRAP_SECRET is not configured" in resp.json()["detail"]


def test_repeat_bootstrap_attempt_rejected(bootstrap_env):
    """Once an administrator is initialized, subsequent bootstrap attempts return HTTP 409 Conflict."""
    client, _ = bootstrap_env

    payload = {
        "email": "admin1@enterprise.com",
        "password": "AdminPassword123!",
        "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
    }
    resp1 = client.post("/api/auth/bootstrap-admin", json=payload)
    assert resp1.status_code == 201

    payload2 = {
        "email": "admin2@enterprise.com",
        "password": "AdminPassword123!",
        "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
    }
    resp2 = client.post("/api/auth/bootstrap-admin", json=payload2)
    assert resp2.status_code == 409
    assert "already been initialized" in resp2.json()["detail"]


def test_concurrent_bootstrap_requests_atomic_lock(bootstrap_env):
    """Concurrent bootstrap requests must only allow ONE initial administrator to be created."""
    reset_auth_rate_limits()
    client, _ = bootstrap_env

    def _attempt_bootstrap(idx: int):
        payload = {
            "email": f"concurrent_admin_{idx}@enterprise.com",
            "password": "AdminPassword123!",
            "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
        }
        return client.post("/api/auth/bootstrap-admin", json=payload)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_attempt_bootstrap, i) for i in range(5)]
        responses = [f.result() for f in futures]

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1, f"Expected exactly 1 HTTP 201, got {status_codes}"
    assert status_codes.count(409) == 4, f"Expected 4 HTTP 409 Conflict, got {status_codes}"


def test_bootstrap_state_persists_across_restart(tmp_path: Path):
    """Application restart does not reset administrator bootstrap state."""
    reset_auth_rate_limits()
    db_path = tmp_path / "persist_test.db"
    settings = _BootstrapTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",
        jwt_secret_key="test-secret-key-for-bootstrap-testing-32bytes!",
        admin_bootstrap_secret="persistent-secret-12345",
    )
    settings.ensure_directories()
    configure_database(settings.database_url)

    # Initial session: bootstrap admin
    app1 = create_app()
    app1.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app1) as client1:
        resp = client1.post(
            "/api/auth/bootstrap-admin",
            json={
                "email": "persistent_admin@firm.com",
                "password": "SecurePassword123!",
                "bootstrap_secret": "persistent-secret-12345",
            },
        )
        assert resp.status_code == 201

    # Simulate server restart by creating a new app instance connecting to the same DB
    app2 = create_app()
    app2.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app2) as client2:
        status_resp = client2.get("/api/auth/bootstrap-status")
        assert status_resp.status_code == 200
        assert status_resp.json()["bootstrapped"] is True

        # Second bootstrap attempt after restart is rejected
        resp2 = client2.post(
            "/api/auth/bootstrap-admin",
            json={
                "email": "another_admin@firm.com",
                "password": "SecurePassword123!",
                "bootstrap_secret": "persistent-secret-12345",
            },
        )
        assert resp2.status_code == 409


def test_bootstrap_validation_rules(bootstrap_env):
    """Verify validation: invalid email format and short password rejection."""
    client, _ = bootstrap_env

    # Invalid email format (HTTP 422)
    resp_bad_email = client.post(
        "/api/auth/bootstrap-admin",
        json={
            "email": "not-an-email",
            "password": "ValidPassword123!",
            "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
        },
    )
    assert resp_bad_email.status_code == 422

    # Short password (HTTP 422)
    resp_short_pw = client.post(
        "/api/auth/bootstrap-admin",
        json={
            "email": "admin@firm.com",
            "password": "short",
            "bootstrap_secret": "correct-bootstrap-secret-phrase-456",
        },
    )
    assert resp_short_pw.status_code == 422
