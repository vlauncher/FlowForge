"""Exponential backoff with full jitter and Retry-After header handling."""

from __future__ import annotations

import random
from random import Random


def compute_backoff_seconds(
    attempt_no: int,
    retry_after: float | None = None,
    rng: Random | None = None,
) -> float:
    """Compute backoff delay with full jitter bounded between 0 and 60s."""
    # 2.0 * 2^(attempt - 1), capped at 60s
    cap = min(60.0, 2.0 * (2 ** max(0, attempt_no - 1)))
    generator = rng if rng is not None else random
    jittered = generator.uniform(0.0, cap)

    if retry_after is not None:
        # Honour Retry-After up to 120s maximum
        return min(120.0, max(jittered, retry_after))

    return jittered
