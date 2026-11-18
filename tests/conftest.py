"""Pytest shared fixtures and authentication test helpers for LegalEase."""

from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.auth.security import create_access_token, hash_password
from backend.database import db as db_module
from backend.database.models import User


def create_test_user(
    email: str = "admin@legalease.com",
    role: str = "admin",
    tenant_id: str = "default_tenant",
    full_name: str = "Admin User",
    secret_key: str = "test-secret-key-12345678901234567890",
) -> tuple[User, str]:
    """Helper to persist a user into the active DB and return (User, JWT_token)."""
    db: Session = db_module.SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                hashed_password=hash_password("SecurePassword123!"),
                full_name=full_name,
                role=role,
                tenant_id=tenant_id,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(
            data={"sub": user.email, "tenant_id": user.tenant_id, "role": user.role},
            secret_key=secret_key,
        )
        return user, token
    finally:
        db.close()
