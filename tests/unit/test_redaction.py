"""Unit tests for secret and PII redaction."""

from __future__ import annotations

from app.core.redaction import redact


def test_redaction_nested_structures() -> None:
    """P1-T13: Nested dict/list with sensitive keys -> '***', input unchanged."""
    original = {
        "user": {
            "email": "alice@example.com",
            "password": "super-secret-password-123",
            "profile": {
                "api_key": "ff_live_99887766",
                "authorization": "Bearer token123",
            },
        },
        "items": [
            {"id": 1, "session_token": "token-abc"},
            {"id": 2, "cookie": "sessionid=xyz"},
        ],
    }

    cleaned = redact(original)

    # Check redacted values
    assert cleaned["user"]["password"] == "***"
    assert cleaned["user"]["profile"]["api_key"] == "***"
    assert cleaned["user"]["profile"]["authorization"] == "***"
    assert cleaned["items"][0]["session_token"] == "***"
    assert cleaned["items"][1]["cookie"] == "***"

    # Non-sensitive keys remain intact
    assert cleaned["user"]["email"] == "alice@example.com"
    assert cleaned["items"][0]["id"] == 1

    # Original is not mutated
    assert original["user"]["password"] == "super-secret-password-123"
    assert original["user"]["profile"]["api_key"] == "ff_live_99887766"


def test_redaction_depth_bounded() -> None:
    """P1-T13: Extremely deep nesting is bounded at max_depth."""
    deep: dict = {"level": 0}
    current = deep
    for i in range(1, 15):
        current["next"] = {"level": i}
        current = current["next"]

    cleaned = redact(deep, max_depth=3)
    assert cleaned["next"]["next"]["next"] == "…"
