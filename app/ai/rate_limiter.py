"""Sliding-window in-memory rate limiter for free LLM tier."""

from __future__ import annotations

import collections
import time

from app.ai.interface import LLMRateLimitedError


class SlidingWindowLimiter:
    """Tracks and enforces free-tier RPM and RPD caps with a sliding timestamp window."""

    def __init__(self, rpm: int = 20, rpd: int = 50) -> None:
        self.rpm = rpm
        self.rpd = rpd
        self._minute_window: collections.deque[float] = collections.deque()
        self._day_window: collections.deque[float] = collections.deque()

    def _prune(self, now: float) -> None:
        minute_cutoff = now - 60.0
        while self._minute_window and self._minute_window[0] <= minute_cutoff:
            self._minute_window.popleft()

        day_cutoff = now - 86400.0
        while self._day_window and self._day_window[0] <= day_cutoff:
            self._day_window.popleft()

    def check(self, now: float | None = None) -> None:
        """Verify that another call does not exceed RPM or RPD limits without consuming a token."""
        curr = now if now is not None else time.time()
        self._prune(curr)

        if len(self._minute_window) >= self.rpm:
            retry_after = max(1, int(60 - (curr - self._minute_window[0])))
            msg = f"LLM_RATE_LIMITED: RPM limit ({self.rpm}) reached. Retry in {retry_after}s."
            raise LLMRateLimitedError(
                msg,
                headers={"Retry-After": str(retry_after)},
            )

        if len(self._day_window) >= self.rpd:
            raise LLMRateLimitedError(
                f"LLM_RATE_LIMITED: free model daily limit ({self.rpd} req/day) reached.",
            )

    def record(self, now: float | None = None) -> None:
        """Record an executed call in the sliding windows."""
        curr = now if now is not None else time.time()
        self._prune(curr)
        self._minute_window.append(curr)
        self._day_window.append(curr)

    def acquire(self, now: float | None = None) -> None:
        """Atomically check and record a call."""
        self.check(now)
        self.record(now)

    def reset(self) -> None:
        """Clear all sliding window history (for tests)."""
        self._minute_window.clear()
        self._day_window.clear()
