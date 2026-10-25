"""Unit tests for cryptographic token helpers and password hashing (P2-T26)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import UnauthenticatedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        app_env="test",
        jwt_secret="test-super-secret-key-at-least-32-chars-long!",
        jwt_issuer="flowforge",
        jwt_audience="flowforge-api",
        access_token_ttl_seconds=300,
    )


def test_password_hash_and_verify() -> None:
    """Argon2id produces verifiable, distinct hashes."""
    pwd = "CorrectHorseBatteryStaple123!"
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)

    assert h1 != h2  # Unique salt per hash
    assert verify_password(pwd, h1) is True
    assert verify_password(pwd, h2) is True
    assert verify_password("WrongPassword123!", h1) is False


def test_access_token_round_trip(auth_settings: Settings) -> None:
    """P2-T26: Valid access token generates and decodes claims cleanly."""
    user_id = uuid4()
    token = create_access_token(user_id, settings=auth_settings)
    payload = decode_access_token(token, settings=auth_settings)

    assert payload["sub"] == str(user_id)
    assert payload["iss"] == auth_settings.jwt_issuer
    assert payload["aud"] == auth_settings.jwt_audience
    assert "jti" in payload
    assert payload["exp"] > time.time()


def test_access_token_tampered_rejected(auth_settings: Settings) -> None:
    """P2-T26: Tampered token payload is rejected."""
    user_id = uuid4()
    token = create_access_token(user_id, settings=auth_settings)
    parts = token.split(".")
    tampered = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"

    with pytest.raises(UnauthenticatedError):
        decode_access_token(tampered, settings=auth_settings)


def test_access_token_alg_none_rejected(auth_settings: Settings) -> None:
    """P2-T26: Insecure alg=none tokens are strictly rejected."""
    payload = {
        "sub": str(uuid4()),
        "iss": auth_settings.jwt_issuer,
        "aud": auth_settings.jwt_audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    insecure_token = jwt.encode(payload, "", algorithm="none")

    with pytest.raises(UnauthenticatedError):
        decode_access_token(insecure_token, settings=auth_settings)


def test_access_token_wrong_key_rejected(auth_settings: Settings) -> None:
    """P2-T26: Token signed with a different key is rejected."""
    user_id = uuid4()
    other_settings = Settings(
        app_env="test",
        jwt_secret="other-different-secret-key-at-least-32-chars!",
    )
    foreign_token = create_access_token(user_id, settings=other_settings)

    with pytest.raises(UnauthenticatedError):
        decode_access_token(foreign_token, settings=auth_settings)


def test_refresh_token_entropy_and_hashing() -> None:
    """Refresh tokens are cryptographically distinct with deterministic sha256."""
    t1 = new_refresh_token()
    t2 = new_refresh_token()

    assert t1 != t2
    assert len(t1) >= 40
    h1 = hash_token(t1)
    assert h1 == hash_token(t1)
    assert len(h1) == 64
