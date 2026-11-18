"""Cryptographic security utilities: Argon2id password hashing and RFC 7519 HS256 JWT tokens."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

logger = logging.getLogger(__name__)

# Argon2id password hasher (winner of the Password Hashing Competition)
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash plaintext password securely using Argon2id."""
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against stored Argon2id hash in constant time."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False
    except Exception as exc:
        logger.warning("Unexpected password verification error: %s", exc)
        return False


def _b64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Decode base64url string with restored padding."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


class JWTError(Exception):
    """Raised when JWT verification or decoding fails."""


def create_access_token(
    data: dict[str, Any],
    secret_key: str,
    algorithm: str = "HS256",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a standard RFC 7519 HMAC-SHA256 JWT access token."""
    if algorithm != "HS256":
        raise ValueError(f"Unsupported algorithm '{algorithm}'. Only HS256 is supported.")

    to_encode = dict(data)
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=1440)  # Default 24 hours

    to_encode["iat"] = int(now.timestamp())
    to_encode["exp"] = int(expire.timestamp())

    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_json = json.dumps(to_encode, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    header_b64 = _b64url_encode(header_json)
    payload_b64 = _b64url_encode(payload_json)

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_access_token(
    token: str,
    secret_key: str,
    algorithm: str = "HS256",
) -> dict[str, Any]:
    """Verify and decode standard RFC 7519 HS256 JWT access token."""
    if not token or not isinstance(token, str):
        raise JWTError("Token must be a non-empty string.")

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise JWTError("Malformed JWT token: expected header, payload, and signature.")

    header_b64, payload_b64, signature_b64 = parts

    try:
        header_bytes = _b64url_decode(header_b64)
        header = json.loads(header_bytes.decode("utf-8"))
    except Exception as exc:
        raise JWTError(f"Invalid JWT header: {exc}") from exc

    if header.get("alg") != algorithm:
        raise JWTError(f"Algorithm mismatch: expected {algorithm}, got {header.get('alg')}.")

    # Validate HMAC signature in constant time
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    if not hmac.compare_digest(signature_b64, expected_sig_b64):
        raise JWTError("Invalid JWT token signature.")

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise JWTError(f"Invalid JWT payload: {exc}") from exc

    # Validate expiration
    exp = payload.get("exp")
    if exp is None:
        raise JWTError("JWT payload missing expiration ('exp') claim.")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts >= exp:
        raise JWTError("JWT token has expired.")

    return payload
