"""ID generation utilities."""

from __future__ import annotations

import uuid


def new_id() -> uuid.UUID:
    """Generate a time-ordered UUIDv7."""
    return uuid.uuid7()
