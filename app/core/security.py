"""Authentication, password hashing, and token cryptography."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any
from uuid import UUID

import argon2
import jwt
from argon2.exceptions import VerificationError, VerifyMismatchError
from jwt.exceptions import PyJWTError

from app.core.config import Settings, get_settings
from app.core.errors import UnauthenticatedError
from app.core.ids import new_id

_hasher = argon2.PasswordHasher()

# Fixed dummy hash for constant-time email enumeration mitigation (P2-T04)
DUMMY_PASSWORD_HASH = _hasher.hash("dummy-flowforge-timing-mitigation-secret")


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2id hash.

    Returns False safely on mismatch without raising.
    """
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False


def check_needs_rehash(hashed_password: str) -> bool:
    """Check if the given password hash needs upgrading."""
    return _hasher.check_needs_rehash(hashed_password)


def verify_dummy_password(password: str) -> None:
    """Run verification against a dummy hash to equalize response times."""
    verify_password(password, DUMMY_PASSWORD_HASH)


def create_access_token(
    user_id: str | UUID,
    *,
    settings: Settings | None = None,
) -> str:
    """Generate a signed JWT access token with all required RFC claims."""
    cfg = settings or get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + cfg.access_token_ttl_seconds,
        "iss": cfg.jwt_issuer,
        "aud": cfg.jwt_audience,
        "jti": str(new_id()),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")


def decode_access_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Enforces issuer, audience, expiration, issued-at, and subject claims.
    Rejects `alg=none` and mismatched keys.
    """
    cfg = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            cfg.jwt_secret,
            algorithms=["HS256"],
            issuer=cfg.jwt_issuer,
            audience=cfg.jwt_audience,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        return payload
    except PyJWTError as err:
        raise UnauthenticatedError("Invalid, expired, or malformed access token") from err


def new_refresh_token() -> str:
    """Generate a secure cryptographic URL-safe refresh token string."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Compute SHA-256 hex digest of a token string for safe database persistence."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()
