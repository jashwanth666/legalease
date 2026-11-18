"""FastAPI authentication, CSRF validation, and role-based access dependencies."""

import hmac
import logging
from typing import Callable
from urllib.parse import urlparse
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.auth.security import JWTError, decode_access_token
from backend.config import Settings, get_settings
from backend.database import User, get_db

logger = logging.getLogger(__name__)

# Standard OAuth2 Bearer security scheme
_bearer_scheme = HTTPBearer(auto_error=False)


def _validate_cookie_csrf(request: Request, settings: Settings) -> None:
    """Enforce CSRF protection for cookie-authenticated mutating requests.

    Requests authenticated via Authorization: Bearer <token> bypass this check,
    as browsers do not automatically attach custom Authorization headers cross-origin.
    Cookie-authenticated mutating requests (POST, PUT, PATCH, DELETE) must provide:
    1. A valid 'csrf_token' cookie and matching 'X-CSRF-Token' header (Double Submit Cookie).
    2. An allowed Origin/Referer header matching configured CORS origins (if provided).
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return

    csrf_cookie = request.cookies.get("csrf_token")
    csrf_header = request.headers.get("x-csrf-token") or request.headers.get("x-csrftoken")

    if not csrf_cookie or not csrf_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: missing CSRF token in cookie or header for cookie-authenticated request.",
        )

    if not hmac.compare_digest(csrf_cookie.strip(), csrf_header.strip()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: token mismatch between cookie and X-CSRF-Token header.",
        )

    # Validate Origin header if present
    origin = request.headers.get("origin")
    if origin:
        allowed = settings.get_allowed_origins()
        # Also allow same-origin requests where origin host matches request host
        request_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin not in allowed and origin != request_origin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"CSRF validation failed: untrusted origin '{origin}'.",
            )


def get_current_user(
    request: Request,
    auth: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Validate JWT token from Authorization header or cookie, returning the authenticated User.

    If authenticated via cookie, automatically enforces CSRF token validation on state-changing methods.
    """
    token: str | None = None
    is_cookie_auth = False

    if auth and auth.credentials:
        token = auth.credentials.strip()
    elif "access_token" in request.cookies:
        token = request.cookies["access_token"].strip()
        is_cookie_auth = True

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce CSRF protection strictly for cookie-authenticated requests
    if is_cookie_auth:
        _validate_cookie_csrf(request, settings)

    try:
        payload = decode_access_token(
            token=token,
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_email = payload.get("sub")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing subject claim ('sub').",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token does not exist.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    """Dependency factory enforcing role-based permissions (Admin, Legal Reviewer, Employee)."""

    def _role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {', '.join(allowed_roles)}. Your role is '{user.role}'.",
            )
        return user

    return _role_checker
