"""Keyset cursor encoding, decoding, and generic pagination container."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.errors import BadRequestError

T = TypeVar("T")


class CursorPayload(BaseModel):
    """Decoded keyset cursor representation."""

    created_at: datetime
    id: UUID


def encode_cursor(created_at: datetime, item_id: UUID | str) -> str:
    """Encode created_at (UTC ISO format) and item UUID into a base64url cursor string."""
    # Ensure timezone is normalized to UTC
    dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    raw = json.dumps({"c": dt.isoformat(), "i": str(item_id)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> CursorPayload:
    """Decode a base64url cursor string back into (created_at, id).

    Raises BadRequestError (HTTP 400) if the cursor is malformed, unparseable,
    or missing expected keys.
    """
    if not cursor or not cursor.strip():
        raise BadRequestError("Cursor cannot be empty")

    # Re-pad base64 string
    padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
    try:
        raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as err:
        raise BadRequestError("Malformed or corrupted pagination cursor") from err

    if not isinstance(data, dict) or "c" not in data or "i" not in data:
        raise BadRequestError("Invalid cursor structure: missing required keys")

    try:
        created_at = datetime.fromisoformat(data["c"])
        item_id = UUID(data["i"])
    except Exception as err:
        raise BadRequestError("Invalid cursor contents: malformed timestamp or UUID") from err

    return CursorPayload(created_at=created_at, id=item_id)


class Page[T](BaseModel):
    """Standard paginated response model."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class PaginationParams(BaseModel):
    """Standard query parameters for cursor-paginated endpoints."""

    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
