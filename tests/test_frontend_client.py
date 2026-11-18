"""Tests for the frontend LegalEaseAPIClient and UI components."""

from unittest.mock import MagicMock, patch
import pytest

from frontend.components.risk_cards import format_location_label, risk_badge_html
from frontend.utils.api_client import APIError, LegalEaseAPIClient


def test_api_client_token_header_injection():
    client = LegalEaseAPIClient(base_url="http://testserver", token="test-token-123")
    assert client.token == "test-token-123"

    with patch.object(client.session, "request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_req.return_value = mock_resp

        res = client._request("GET", "/api/test")
        assert res.status_code == 200

        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer test-token-123"


def test_api_client_set_token():
    client = LegalEaseAPIClient(base_url="http://testserver")
    assert client.token is None
    client.set_token("new-jwt-token")
    assert client.token == "new-jwt-token"

    with patch.object(client.session, "request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_req.return_value = mock_resp

        client._request("GET", "/api/secure")
        _, kwargs = mock_req.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer new-jwt-token"


def test_api_client_login_and_register_flow():
    client = LegalEaseAPIClient(base_url="http://testserver")

    with patch.object(client.session, "request") as mock_req:
        # Mock register response
        mock_reg_resp = MagicMock()
        mock_reg_resp.status_code = 201
        mock_reg_resp.json.return_value = {
            "id": "u-123",
            "email": "user@firm.com",
            "role": "legal_reviewer",
            "tenant_id": "test_tenant",
        }

        # Mock login response
        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 200
        mock_login_resp.json.return_value = {
            "access_token": "token-abc-xyz",
            "token_type": "bearer",
            "expires_in": 86400,
        }

        # Mock me response
        mock_me_resp = MagicMock()
        mock_me_resp.status_code = 200
        mock_me_resp.json.return_value = {
            "id": "u-123",
            "email": "user@firm.com",
            "full_name": "Test User",
            "role": "legal_reviewer",
            "tenant_id": "test_tenant",
        }

        mock_req.side_effect = [mock_reg_resp, mock_login_resp, mock_me_resp]

        reg = client.register(
            email="user@firm.com",
            password="securepassword123",
            full_name="Test User",
            role="legal_reviewer",
            tenant_id="test_tenant",
        )
        assert reg["email"] == "user@firm.com"

        login = client.login("user@firm.com", "securepassword123")
        assert login["access_token"] == "token-abc-xyz"
        assert client.token == "token-abc-xyz"

        me = client.get_me()
        assert me["full_name"] == "Test User"
        assert me["tenant_id"] == "test_tenant"


def test_api_client_error_handling():
    client = LegalEaseAPIClient(base_url="http://testserver")

    with patch.object(client.session, "request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"detail": "Invalid credentials"}
        mock_req.return_value = mock_resp

        with pytest.raises(APIError) as exc_info:
            client.login("bad@user.com", "wrongpass")
        assert exc_info.value.status_code == 401
        assert "Invalid credentials" in exc_info.value.message


def test_risk_card_components():
    badge = risk_badge_html("critical")
    assert "le-badge-critical" in badge
    assert "CRITICAL" in badge

    badge_unknown = risk_badge_html("unspecified")
    assert "le-badge-no_notable_risk" in badge_unknown

    loc_pdf = format_location_label({"page_number": 3})
    assert loc_pdf == "Page 3"

    loc_docx = format_location_label({"location_type": "docx_paragraph", "paragraph_index": 12})
    assert loc_docx == "DOCX Para 12"
