"""Pydantic request and response schemas for authentication and user management."""

from datetime import datetime
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


UserRole = Literal["admin", "legal_reviewer", "employee"]


class UserRegisterRequest(BaseModel):
    """Registration payload for creating a new tenant-scoped user."""

    email: str = Field(..., description="Valid corporate or user email address.")
    password: str = Field(..., min_length=8, description="Secure password (minimum 8 characters).")
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = Field(default="employee", description="Role: admin, legal_reviewer, or employee.")
    tenant_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional organization/tenant ID. Defaults to derived email domain or 'default_tenant'.",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email format.")
        return clean

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return v


class UserLoginRequest(BaseModel):
    """User credentials for obtaining JWT access token."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    """Safe public user profile without sensitive credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None = None
    role: str
    tenant_id: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT bearer token and authenticated user profile."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
