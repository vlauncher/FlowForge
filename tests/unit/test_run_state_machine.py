"""Unit tests for the Run State Machine (P4-T01)."""

import pytest

from app.domain.run_state_machine import (
    InvalidStateTransitionError,
    can_transition,
    is_terminal,
    transition,
)


def test_valid_transitions_r1_to_r11() -> None:
    # R1: create
    assert transition(None, "create") == "QUEUED"

    # R2: claim
    assert transition("QUEUED", "claim") == "RUNNING"

    # R3: reclaim
    assert transition("RUNNING", "reclaim") == "RUNNING"

    # R4: needs approval
    assert transition("RUNNING", "needs_approval") == "WAITING_APPROVAL"

    # R5: approved
    assert transition("WAITING_APPROVAL", "approved") == "QUEUED"

    # R6: all steps done
    assert transition("RUNNING", "all_steps_done") == "SUCCEEDED"

    # R7: step failed finally
    assert transition("RUNNING", "step_failed") == "FAILED"

    # R8: approval rejected or expired
    assert transition("WAITING_APPROVAL", "approval_rejected") == "FAILED"
    assert transition("WAITING_APPROVAL", "approval_expired") == "FAILED"

    # R9: cancel from queued or waiting
    assert transition("QUEUED", "cancel") == "CANCELLED"
    assert transition("WAITING_APPROVAL", "cancel") == "CANCELLED"

    # R10: cancel requested during execution
    assert transition("RUNNING", "cancel_requested") == "CANCELLED"

    # R11: manual retry from FAILED
    assert transition("FAILED", "retry") == "QUEUED"


def test_illegal_transitions_rejected() -> None:
    # SUCCEEDED is terminal
    with pytest.raises(InvalidStateTransitionError):
        transition("SUCCEEDED", "claim")
    with pytest.raises(InvalidStateTransitionError):
        transition("SUCCEEDED", "reclaim")
    with pytest.raises(InvalidStateTransitionError):
        transition("SUCCEEDED", "retry")
    with pytest.raises(InvalidStateTransitionError):
        transition("SUCCEEDED", "cancel")

    # CANCELLED is terminal
    with pytest.raises(InvalidStateTransitionError):
        transition("CANCELLED", "claim")
    with pytest.raises(InvalidStateTransitionError):
        transition("CANCELLED", "retry")

    # FAILED cannot immediately succeed without running
    with pytest.raises(InvalidStateTransitionError):
        transition("FAILED", "all_steps_done")


def test_terminal_states() -> None:
    assert is_terminal("SUCCEEDED") is True
    assert is_terminal("CANCELLED") is True
    assert is_terminal("FAILED") is False  # can be manually retried (R11)
    assert is_terminal("RUNNING") is False
    assert is_terminal("QUEUED") is False
    assert is_terminal("WAITING_APPROVAL") is False


def test_can_transition() -> None:
    assert can_transition(None, "QUEUED") is True
    assert can_transition("QUEUED", "RUNNING") is True
    assert can_transition("RUNNING", "SUCCEEDED") is True
    assert can_transition("SUCCEEDED", "RUNNING") is False
    assert can_transition("CANCELLED", "RUNNING") is False
