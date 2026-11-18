"""Dedicated HTTP client for communicating between Streamlit and the FastAPI backend."""

import os
from typing import Any

import requests


DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


class APIError(Exception):
    """Raised when the FastAPI backend returns an error or cannot be reached."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LegalEaseAPIClient:
    """Synchronous REST client for LegalEase FastAPI endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | tuple[float, float] = (10.0, 180.0),
    ) -> None:
        self.base_url = (base_url or DEFAULT_API_BASE_URL).rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        if "127.0.0.1" in self.base_url or "localhost" in self.base_url:
            self.session.trust_env = False

    def set_token(self, token: str | None) -> None:
        self.token = token

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        headers = dict(kwargs.get("headers") or {})
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"
        kwargs["headers"] = headers
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.Timeout as exc:
            raise APIError(
                f"Request timed out waiting for LegalEase backend ({path}). Large documents may require more time."
            ) from exc
        except requests.RequestException as exc:
            raise APIError(
                f"Unable to reach LegalEase backend at {self.base_url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = f"Request failed with status {response.status_code}."
            try:
                body = response.json()
                if isinstance(body, dict) and "detail" in body:
                    detail = str(body["detail"])
            except Exception:
                if response.text:
                    detail = response.text[:300]
            raise APIError(detail, status_code=response.status_code)

        return response

    def register(
        self,
        email: str,
        password: str,
        full_name: str,
        role: str = "employee",
        tenant_id: str = "default_tenant",
    ) -> dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "full_name": full_name,
            "role": role,
            "tenant_id": tenant_id,
        }
        return self._request("POST", "/api/auth/register", json=payload).json()

    def login(self, email: str, password: str) -> dict[str, Any]:
        payload = {"email": email, "password": password}
        res = self._request("POST", "/api/auth/login", json=payload).json()
        token = res.get("access_token")
        if token:
            self.set_token(token)
        return res

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/api/auth/me").json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=5.0).json()

    def upload_document(
        self, filename: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> dict[str, Any]:
        files = {"file": (filename, content, content_type)}
        return self._request("POST", "/api/upload", files=files).json()

    def list_documents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/documents").json()

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/documents/{document_id}").json()

    def analyze_document(self, document_id: str, wait: bool = False) -> dict[str, Any]:
        params = {"wait": "true"} if wait else {}
        return self._request("POST", f"/api/analyze/{document_id}", params=params).json()

    def get_status(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/status/{document_id}").json()

    def get_analysis(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/analysis/{document_id}").json()

    def get_clauses(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/clauses/{document_id}").json()

    def get_metadata(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/metadata/{document_id}").json()

    def get_comparisons(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/compare/{document_id}").json()

    def list_reports(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/reports").json()

    def download_report_bytes(self, document_id: str) -> bytes:
        return self._request("GET", f"/api/report/{document_id}").content

    def delete_document(self, document_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/documents/{document_id}").json()

    def rebuild_templates(self) -> dict[str, Any]:
        return self._request("POST", "/api/templates/rebuild").json()

