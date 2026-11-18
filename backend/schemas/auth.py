"""Pydantic request and response schemas for authentication and user management."""

from datetime import datetime
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


UserRole = Literal["admin", "legal_reviewer", "employee"]


class UserRegisterRequest(BaseModel):
    """Registration payload for creating a new tenant-scoped user account."""

    email: str = Field(..., description="Valid corporate or user email address.")
    password: str = Field(..., min_length=8, description="Secure password (minimum 8 characters).")
    full_name: str | None = Field(default=None, max_length=255)
    role: str = Field(
        default="employee",
        description="Public registration is restricted to 'employee'. Privileged roles require admin invitation.",
    )
    tenant_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional organization/tenant ID for a new workspace.",
    )

    @field_validator("role")
    @classmethod
    def forbid_public_privileged_roles(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("employee", ""):
            raise ValueError(
                "Public self-registration only permits creating Employee accounts. "
                "Privileged roles (admin, legal_reviewer) must be provisioned by an organization administrator."
            )
        return "employee"

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


class AdminCreateUserRequest(BaseModel):
    """Admin-only payload for provisioning users within their own tenant organization."""

    email: str = Field(..., description="Corporate email for the new user.")
    password: str = Field(..., min_length=8, description="Initial secure password.")
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = Field(
        default="employee",
        description="Assigned role: admin, legal_reviewer, or employee.",
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
