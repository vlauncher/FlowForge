"""Unit tests for Settings validation and parsing."""

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_cors_origins_parsing_and_validation() -> None:
    """P1-T11: Wildcard forbidden, comma list parsed, non-HTTP forbidden."""
    # Valid comma list
    s1 = Settings(api_cors_origins="http://localhost:3000, https://app.flowforge.dev")
    assert s1.api_cors_origins == ["http://localhost:3000", "https://app.flowforge.dev"]

    # Wildcard forbidden
    with pytest.raises(ValueError, match="Wildcard"):
        Settings(api_cors_origins="*")

    with pytest.raises(ValueError, match="Wildcard"):
        Settings(api_cors_origins=["http://localhost:5173", "*"])

    # Non-HTTP forbidden
    with pytest.raises(ValueError, match="must start with http:// or https://"):
        Settings(api_cors_origins=["ftp://evil.com"])


def test_max_request_bytes_validation() -> None:
    """P1-T11: MAX_REQUEST_BYTES=0 or negative raises."""
    with pytest.raises(ValueError, match="greater than 0"):
        Settings(max_request_bytes=0)

    with pytest.raises(ValueError, match="greater than 0"):
        Settings(max_request_bytes=-10)

    s = Settings(max_request_bytes=500)
    assert s.max_request_bytes == 500
