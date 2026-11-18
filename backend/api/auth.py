"""Authentication and user management REST API endpoints with brute-force rate limiting."""

from datetime import datetime, timedelta, timezone
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user
from backend.auth.security import create_access_token, hash_password, verify_password
from backend.config import Settings, get_settings
from backend.database import User, get_db
from backend.schemas.auth import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Simple in-memory sliding window rate limiter: IP -> list of timestamps
_auth_rate_limits: dict[str, list[float]] = {}
MAX_AUTH_ATTEMPTS = 15
AUTH_WINDOW_SECONDS = 60.0


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    attempts = _auth_rate_limits.setdefault(client_ip, [])
    # Filter attempts within the window
    _auth_rate_limits[client_ip] = [t for t in attempts if now - t < AUTH_WINDOW_SECONDS]
    if len(_auth_rate_limits[client_ip]) >= MAX_AUTH_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please wait 60 seconds before retrying.",
        )
    _auth_rate_limits[client_ip].append(now)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    request: Request,
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user account with secure Argon2id password hashing and tenant isolation."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{payload.email}' already exists.",
        )

    # Derive default tenant if not specified
    tenant = payload.tenant_id
    if not tenant or not tenant.strip():
        # Derive tenant from email domain if possible
        domain = payload.email.split("@")[-1].split(".")[0]
        tenant = f"tenant_{domain}" if domain and domain not in ("gmail", "yahoo", "hotmail", "outlook") else "default_tenant"

    hashed_pw = hash_password(payload.password)
    user = User(
        email=payload.email,
        hashed_password=hashed_pw,
        full_name=payload.full_name,
        role=payload.role,
        tenant_id=tenant.strip(),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("New user registered: %s (role: %s, tenant: %s)", user.email, user.role, user.tenant_id)
    return user


@router.post("/login", response_model=TokenResponse)
def login_user(
    request: Request,
    response: Response,
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Authenticate email and password, issuing an RFC 7519 HS256 JWT access token."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact an organization administrator.",
        )

    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    token_claims = {
        "sub": user.email,
        "uid": user.id,
        "role": user.role,
        "tenant_id": user.tenant_id,
    }
    access_token = create_access_token(
        data=token_claims,
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_delta=expires_delta,
    )

    # Also set secure cookie for frontend Streamlit / browser sessions
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        samesite="lax",
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Retrieve authenticated user's profile and organization context."""
    return current_user
