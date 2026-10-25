"""Unit tests for the external tool Circuit Breaker (P5-T03)."""

from app.infrastructure.http_tool.circuit_breaker import CircuitBreaker


def test_circuit_breaker_transitions() -> None:
    breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=0.1)
    provider = "api.example.com"

    # Initial state is CLOSED
    assert breaker.get_state(provider) == "CLOSED"
    assert breaker.can_execute(provider) is True

    # 4 failures: remains CLOSED
    for _ in range(4):
        breaker.record_failure(provider)
    assert breaker.get_state(provider) == "CLOSED"
    assert breaker.can_execute(provider) is True

    # 5th failure: trips to OPEN
    breaker.record_failure(provider)
    assert breaker.get_state(provider) == "OPEN"
    assert breaker.can_execute(provider) is False

    # While OPEN within cooldown: blocked
    assert breaker.can_execute(provider) is False

    # Simulate cooldown passing: state becomes HALF_OPEN
    b_state = breaker._states[provider]
    b_state.opened_at -= 0.2

    assert breaker.get_state(provider) == "HALF_OPEN"
    assert breaker.can_execute(provider) is True

    # Failure in HALF_OPEN trips back to OPEN immediately
    breaker.record_failure(provider)
    assert breaker.get_state(provider) == "OPEN"
    assert breaker.can_execute(provider) is False

    # Cooldown passes again -> HALF_OPEN
    b_state.opened_at -= 0.2
    assert breaker.get_state(provider) == "HALF_OPEN"

    # Success in HALF_OPEN closes the circuit
    breaker.record_success(provider)
    assert breaker.get_state(provider) == "CLOSED"
    assert breaker.can_execute(provider) is True
    assert b_state.consecutive_failures == 0
