"""Unit tests for keyset cursor codec (P2-T27)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.errors import BadRequestError
from app.core.pagination import decode_cursor, encode_cursor


def test_cursor_round_trip() -> None:
    """P2-T27: Valid timestamp and UUID round-trip accurately through cursor codec."""
    now = datetime(2026, 10, 25, 12, 34, 56, 789123, tzinfo=UTC)
    item_id = uuid4()

    cursor = encode_cursor(now, item_id)
    assert isinstance(cursor, str)
    assert "=" not in cursor  # Unpadded base64url

    decoded = decode_cursor(cursor)
    assert decoded.id == item_id
    assert decoded.created_at == now


@pytest.mark.parametrize(
    "bad_cursor",
    [
        "",
        "   ",
        "not-valid-base64!@#$",
        "eyJjIjogIjIwMjYtMTAtMjUifQ",  # missing "i"
        "eyJpIjogIjEyMzQ1In0",  # missing "c"
        "eyJjIjogImJBRC1EQVRFIiwgImkiOiAiMTIzNDUifQ",  # bad date
        "eyJjIjogIjIwMjYtMTAtMjVUMDA6MDA6MDBaIiwgImkiOiAibm90LWEtdXVpZCJ9",  # bad uuid
    ],
)
def test_malformed_cursor_raises_bad_request(bad_cursor: str) -> None:
    """P2-T27: Corrupted or missing cursor fields raise HTTP 400 BadRequestError."""
    with pytest.raises(BadRequestError):
        decode_cursor(bad_cursor)
