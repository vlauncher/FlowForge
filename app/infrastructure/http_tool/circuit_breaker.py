"""In-memory circuit breaker per external tool provider."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]

FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 30.0


@dataclass
class ProviderBreakerState:
    state: CircuitState = "CLOSED"
    consecutive_failures: int = 0
    opened_at: float = 0.0


class CircuitBreaker:
    """Manages failure tracking and half-open transitions per provider host/name."""

    def __init__(
        self,
        failure_threshold: int = FAILURE_THRESHOLD,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, ProviderBreakerState] = {}

    def get_state(self, provider: str) -> CircuitState:
        now = time.monotonic()
        b_state = self._states.get(provider)
        if not b_state:
            return "CLOSED"

        if b_state.state == "OPEN":
            if now - b_state.opened_at >= self.cooldown_seconds:
                b_state.state = "HALF_OPEN"
                return "HALF_OPEN"
            return "OPEN"

        return b_state.state

    def can_execute(self, provider: str) -> bool:
        """Return True if calls to provider are currently permitted."""
        return self.get_state(provider) != "OPEN"

    def record_success(self, provider: str) -> None:
        """Reset failures and close circuit upon successful execution."""
        b_state = self._states.setdefault(provider, ProviderBreakerState())
        b_state.state = "CLOSED"
        b_state.consecutive_failures = 0
        b_state.opened_at = 0.0

    def record_failure(self, provider: str) -> None:
        """Record a 5xx or timeout failure, potentially tripping the circuit."""
        b_state = self._states.setdefault(provider, ProviderBreakerState())
        if b_state.state == "HALF_OPEN":
            # Trial request failed -> re-open circuit
            b_state.state = "OPEN"
            b_state.opened_at = time.monotonic()
            return

        b_state.consecutive_failures += 1
        if b_state.consecutive_failures >= self.failure_threshold:
            b_state.state = "OPEN"
            b_state.opened_at = time.monotonic()

    def reset_all(self) -> None:
        """Clear all provider states (for test isolation)."""
        self._states.clear()


# Global in-memory circuit breaker instance
circuit_breaker = CircuitBreaker()
