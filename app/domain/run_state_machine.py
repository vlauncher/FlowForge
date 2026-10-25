"""Run State Machine (pure domain, zero framework or DB dependencies).

Implements the workflow_runs state transitions R1–R11 specified in spec/00-global.md §4.
"""

from __future__ import annotations

from typing import Literal

RunState = Literal[
    "QUEUED",
    "RUNNING",
    "WAITING_APPROVAL",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
]

TERMINAL_STATES: frozenset[RunState] = frozenset({"SUCCEEDED", "CANCELLED"})

VALID_STATES: frozenset[RunState] = frozenset(
    {"QUEUED", "RUNNING", "WAITING_APPROVAL", "SUCCEEDED", "FAILED", "CANCELLED"}
)


class InvalidStateTransitionError(Exception):
    """Raised when a state transition is not allowed by the state machine."""

    def __init__(self, from_state: RunState | None, event: str, message: str | None = None) -> None:
        self.from_state = from_state
        self.event = event
        detail = message or f"Invalid transition from state '{from_state}' with event '{event}'"
        super().__init__(detail)


# Valid transition table: (from_state, event) -> to_state
_TRANSITIONS: dict[tuple[RunState | None, str], RunState] = {
    # R1: create
    (None, "create"): "QUEUED",
    # R2: claim
    ("QUEUED", "claim"): "RUNNING",
    # R3: reclaim
    ("RUNNING", "reclaim"): "RUNNING",
    # R4: needs approval
    ("RUNNING", "needs_approval"): "WAITING_APPROVAL",
    # R5: approved
    ("WAITING_APPROVAL", "approved"): "QUEUED",
    # R6: all steps done
    ("RUNNING", "all_steps_done"): "SUCCEEDED",
    # R7: step failed finally
    ("RUNNING", "step_failed"): "FAILED",
    # R8: approval rejected or expired
    ("WAITING_APPROVAL", "approval_rejected"): "FAILED",
    ("WAITING_APPROVAL", "approval_expired"): "FAILED",
    # R9: cancel before worker execution / waiting
    ("QUEUED", "cancel"): "CANCELLED",
    ("WAITING_APPROVAL", "cancel"): "CANCELLED",
    # R10: cancel requested during execution
    ("RUNNING", "cancel_requested"): "CANCELLED",
    # R11: manual retry from FAILED
    ("FAILED", "retry"): "QUEUED",
}


def transition(from_state: RunState | None, event: str) -> RunState:
    """Evaluate transition from `from_state` given `event`."""
    target = _TRANSITIONS.get((from_state, event))
    if target is None:
        raise InvalidStateTransitionError(from_state, event)
    return target


def can_transition(from_state: RunState | None, to_state: RunState) -> bool:
    """Return True if there exists any valid transition from `from_state` to `to_state`."""
    return any(
        s_from == from_state and s_to == to_state for (s_from, _), s_to in _TRANSITIONS.items()
    )


def is_terminal(state: RunState) -> bool:
    """Return True if state is permanently terminal."""
    return state in TERMINAL_STATES
