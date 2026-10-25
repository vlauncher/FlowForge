"""Unit tests for exponential backoff with full jitter (P5-T02)."""

import random

from app.infrastructure.http_tool.backoff import compute_backoff_seconds


def test_backoff_bounds_and_exponential_growth() -> None:
    rng = random.Random(42)

    # Attempt 1: cap = min(60, 2.0 * 2^0) = 2.0s
    for _ in range(50):
        val = compute_backoff_seconds(1, rng=rng)
        assert 0.0 <= val <= 2.0

    # Attempt 2: cap = min(60, 2.0 * 2^1) = 4.0s
    for _ in range(50):
        val = compute_backoff_seconds(2, rng=rng)
        assert 0.0 <= val <= 4.0

    # Attempt 6: cap = min(60, 2.0 * 2^5) = 60.0s (capped)
    for _ in range(50):
        val = compute_backoff_seconds(6, rng=rng)
        assert 0.0 <= val <= 60.0

    # Attempt 10: cap = 60.0s
    for _ in range(50):
        val = compute_backoff_seconds(10, rng=rng)
        assert 0.0 <= val <= 60.0


def test_retry_after_handling() -> None:
    rng = random.Random(123)

    # Retry-After larger than random draw is respected
    val = compute_backoff_seconds(1, retry_after=15.0, rng=rng)
    assert val >= 15.0

    # Retry-After capped at 120.0s
    val_capped = compute_backoff_seconds(1, retry_after=300.0, rng=rng)
    assert val_capped == 120.0
