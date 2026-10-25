"""Unit tests for UUIDv7 generation."""

from __future__ import annotations

import time

from app.core.ids import new_id


def test_uuid7_generation_and_monotonicity() -> None:
    """P1-T14: new_id() returns UUID version 7; 1000 IDs are unique and sortable."""
    ids = []
    for _ in range(1000):
        ids.append(new_id())

    # Check version
    for uid in ids:
        assert uid.version == 7

    # Check uniqueness
    assert len(set(ids)) == 1000

    # Check time-ordered sortability across small sleep boundaries
    id1 = new_id()
    time.sleep(0.005)
    id2 = new_id()
    assert id1 < id2
