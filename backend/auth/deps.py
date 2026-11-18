"""FastAPI authentication and role-based access dependencies."""

import logging
from typing import Callable
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.auth.security import JWTError, decode_access_token
from backend.config import Settings, get_settings
from backend.database import User, get_db

logger = logging.getLogger(__name__)

# Standard OAuth2 Bearer security scheme
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    auth: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Validate JWT token from Authorization header or cookie, returning the authenticated User."""
    token: str | None = None
    if auth and auth.credentials:
        token = auth.credentials.strip()
    elif "access_token" in request.cookies:
        token = request.cookies["access_token"].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
