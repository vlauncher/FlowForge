"""Property-based testing for graph validation invariants using Hypothesis (P3-T11)."""

from __future__ import annotations

from typing import Any

import hypothesis.strategies as st
from hypothesis import given, settings

from app.domain.graph_validator import validate_definition


@st.composite
def random_workflow_definition(draw: st.DrawFn) -> dict[str, Any]:
    """Generate syntactically plausible directed graphs of 1 to 20 nodes."""
    node_count = draw(st.integers(min_value=1, max_value=15))
    step_ids = [f"step_{i}" for i in range(node_count)]

    # Draw start step
    start_id = draw(st.sampled_from(step_ids))

    steps: list[dict[str, Any]] = []
    for sid in step_ids:
        # Choose a target for next: another step or None (termination)
        target = draw(st.sampled_from([None] + step_ids))
        steps.append(
            {
                "id": sid,
                "type": "set_data",
                "config": {"values": {"index": sid}},
                "next": target,
            }
        )

    return {
        "schema_version": 1,
        "name": "Random Graph",
        "start": start_id,
        "steps": steps,
    }


@settings(max_examples=500, deadline=None)
@given(wf=random_workflow_definition())
def test_graph_properties_invariant(wf: dict[str, Any]) -> None:
    """P3-T11: validate_definition never crashes and accepted graphs satisfy strict DAG invariants."""
    issues = validate_definition(wf)

    # 1. Never raises an unhandled exception (implicit by reaching here)
    assert isinstance(issues, list)

    # 2. If graph has zero issues, it must strictly be an acyclic terminating DAG where all nodes are reachable
    if len(issues) == 0:
        step_ids = {s["id"] for s in wf["steps"]}
        adj = {s["id"]: s["next"] for s in wf["steps"]}

        # Reachability from start
        reachable = set()
        curr = wf["start"]
        visited = set()
        while curr is not None and curr not in visited:
            visited.add(curr)
            reachable.add(curr)
            curr = adj.get(curr)

        assert reachable == step_ids, "Every step must be reachable in an accepted graph"
        assert any(s["next"] is None for s in wf["steps"]), "At least one step must terminate"
