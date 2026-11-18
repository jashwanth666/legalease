"""Authentication and user management REST API endpoints with brute-force rate limiting."""

from datetime import datetime, timedelta, timezone
import hmac
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.deps import get_current_user, require_roles
from backend.auth.security import create_access_token, hash_password, verify_password
from backend.config import Settings, get_settings
from backend.database import Document, SystemSetting, User, get_db
from backend.schemas.auth import (
    AdminBootstrapRequest,
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    BootstrapStatusResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.services.rate_limiter import RateLimitExceeded, get_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Rate limiter instance — initialized lazily on first request so that the
# settings (including REDIS_URL) are available.  For tests, call
# ``reset_auth_rate_limits()`` to clear all windows between test cases.
_rate_limiter = None


def _get_limiter():
    global _rate_limiter  # noqa: PLW0603
    if _rate_limiter is None:
        _rate_limiter = get_rate_limiter(get_settings(), max_attempts=60, window_seconds=60.0)
    return _rate_limiter


def reset_auth_rate_limits() -> None:
    """Reset rate limiter state (for testing and administrative use)."""
    _get_limiter().reset()


def _check_rate_limit(action: str, client_ip: str) -> None:
    try:
        _get_limiter().check(action, client_ip)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def get_bootstrap_status(db: Session = Depends(get_db)):
    """Check whether initial system administrator setup has been completed."""
    admin_exists = db.query(User).filter(User.role == "admin").first() is not None
    setting_exists = db.query(SystemSetting).filter(SystemSetting.key == "admin_bootstrapped").first() is not None
    is_bootstrapped = admin_exists or setting_exists
    msg = "Administrator has already been configured." if is_bootstrapped else "Administrator setup required."
    return BootstrapStatusResponse(bootstrapped=is_bootstrapped, message=msg)


@router.post("/bootstrap-admin", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_system_admin(
    request: Request,
    payload: AdminBootstrapRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Secure, one-time administrator initialization mechanism using a server bootstrap secret.

    Guarantees atomic, single-execution provisioning of the first system administrator.
    Rejects repeat initialization attempts permanently.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit("bootstrap", client_ip)

    configured_secret = (settings.admin_bootstrap_secret or "").strip()
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator bootstrap is disabled or ADMIN_BOOTSTRAP_SECRET is not configured on this server.",
        )

    # Constant-time comparison prevents timing attacks
    provided_secret = payload.bootstrap_secret.strip()
    if not hmac.compare_digest(provided_secret.encode("utf-8"), configured_secret.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator bootstrap secret.",
        )

    # Check whether an admin already exists or setup was previously completed
    admin_exists = db.query(User).filter(User.role == "admin").first()
    setting_exists = db.query(SystemSetting).filter(SystemSetting.key == "admin_bootstrapped").first()
    if admin_exists or setting_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System administrator has already been initialized. Bootstrap is permanently disabled.",
        )

    # Check duplicate email
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{payload.email}' already exists.",
        )

    # Atomic database lock via primary key constraint on SystemSetting
    try:
        bootstrap_lock = SystemSetting(
            key="admin_bootstrapped",
            value=payload.email,
        )
        db.add(bootstrap_lock)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System administrator has already been initialized. Bootstrap is permanently disabled.",
        )

    assigned_tenant = (payload.tenant_id or "tenant_admin").strip()
    hashed_pw = hash_password(payload.password)
    admin_user = User(
        email=payload.email,
        hashed_password=hashed_pw,
        full_name=payload.full_name,
        role="admin",
        tenant_id=assigned_tenant,
        is_active=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    logger.info("System administrator initialized successfully for %s in tenant %s", admin_user.email, admin_user.tenant_id)
    return admin_user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    request: Request,
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new employee user account with secure Argon2id password hashing and tenant isolation.

    Public self-registration strictly assigns the 'employee' role.
    It NEVER assigns the administrator role, even in an empty database.
    Self-registration into an existing tenant is strictly forbidden to prevent unauthorized infiltration.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit("bootstrap", client_ip)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{payload.email}' already exists.",
        )

    # Public registration is strictly employee — always auto-generate a unique tenant.
    # The client-supplied tenant_id is intentionally ignored: server controls all assignment.
    assigned_role = "employee"
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
    _check_rate_limit("bootstrap", client_ip)

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


@router.post("/logout")
def logout_user(response: Response):
    """Clear session authentication cookie securely."""
    response.delete_cookie(
        key="access_token",
        httponly=True,
        samesite="lax",
    )
    return {"status": "ok", "message": "Successfully logged out."}


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


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_tenant_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Update user role or active status with safeguard against deactivating the last active administrator."""
    target_user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
    ).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found in your organization.",
        )

    # Safeguard: Do not allow deactivating or demoting the last active administrator of the tenant
    if target_user.role == "admin":
        is_demoting = payload.role is not None and payload.role != "admin"
        is_deactivating = payload.is_active is False
        if is_demoting or is_deactivating:
            active_admin_count = (
                db.query(User)
                .filter(
                    User.tenant_id == current_user.tenant_id,
                    User.role == "admin",
                    User.is_active.is_(True),
                )
                .count()
            )
            if active_admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot deactivate or demote the last active administrator for organization '{current_user.tenant_id}'.",
                )

    if payload.is_active is not None:
        target_user.is_active = payload.is_active
    if payload.role is not None:
        target_user.role = payload.role

    db.commit()
    db.refresh(target_user)
    logger.info(
        "Admin %s updated user %s (role: %s, active: %s)",
        current_user.email,
        target_user.email,
        target_user.role,
        target_user.is_active,
    )
    return target_user
