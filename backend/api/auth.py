"""Authentication and user management REST API endpoints with brute-force rate limiting."""

from datetime import datetime, timedelta, timezone
import logging
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user, require_roles
from backend.auth.security import create_access_token, hash_password, verify_password
from backend.config import Settings, get_settings
from backend.database import User, get_db
from backend.schemas.auth import (
    AdminCreateUserRequest,
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
    """Register a new user account with secure Argon2id password hashing and tenant isolation.

    Public self-registration strictly assigns the 'employee' role.
    If no users exist in the entire database, the very first user is bootstrapped as system 'admin'.
    Self-registration into an existing tenant is forbidden to prevent unauthorized tenant infiltration.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{payload.email}' already exists.",
        )

    # Initial system bootstrap check: if database has zero users, first user becomes admin
    user_count = db.query(User).count()
    if user_count == 0:
        assigned_role = "admin"
        tenant = (payload.tenant_id or "default_tenant").strip()
        logger.warning("System bootstrap: Provisioning initial administrator account for %s in tenant %s", payload.email, tenant)
    else:
        assigned_role = "employee"
        tenant_candidate = (payload.tenant_id or "").strip()
        if tenant_candidate:
            # Check if this tenant already has users registered
            tenant_users = db.query(User).filter(User.tenant_id == tenant_candidate).first()
            if tenant_users:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Tenant organization '{tenant_candidate}' already exists. Self-registration into an existing "
                        "organization is prohibited. Please contact your organization administrator for an invitation."
                    ),
                )
            tenant = tenant_candidate
        else:
            # Generate a new unique workspace tenant for the employee
            domain = payload.email.split("@")[-1].split(".")[0]
            clean_domain = f"tenant_{domain}" if domain and domain not in ("gmail", "yahoo", "hotmail", "outlook") else None
            if clean_domain and not db.query(User).filter(User.tenant_id == clean_domain).first():
                tenant = clean_domain
            else:
                tenant = f"tenant_{uuid.uuid4().hex[:8]}"

    hashed_pw = hash_password(payload.password)
    user = User(
        email=payload.email,
        hashed_password=hashed_pw,
        full_name=payload.full_name,
        role=assigned_role,
        tenant_id=tenant,
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

    # Secure cookie flag: enforce HTTPS security in production or when accessed via HTTPS
    is_secure = (
        settings.cookie_secure
        or settings.environment.lower() == "production"
        or request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_secure,
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


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(
    payload: AdminCreateUserRequest,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Provision a new user account within the administrator's authorized tenant organization."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{payload.email}' already exists.",
        )

    hashed_pw = hash_password(payload.password)
    new_user = User(
        email=payload.email,
        hashed_password=hashed_pw,
        full_name=payload.full_name,
        role=payload.role,
        tenant_id=current_user.tenant_id,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(
        "Admin %s created user %s with role %s in tenant %s",
        current_user.email,
        new_user.email,
        new_user.role,
        new_user.tenant_id,
    )
    return new_user


@router.get("/users", response_model=list[UserResponse])
def list_tenant_users(
    current_user: User = Depends(require_roles("admin", "legal_reviewer")),
    db: Session = Depends(get_db),
):
    """List all registered users within the current user's authorized tenant organization."""
    return db.query(User).filter(User.tenant_id == current_user.tenant_id).order_by(User.id.asc()).all()
