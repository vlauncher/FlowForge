"""Unit tests for deterministic graph validator rules (P3-T02 to P3-T10)."""

from __future__ import annotations

import uuid

from app.domain.graph_validator import validate_definition


def sample_support_ticket_definition() -> dict:
    """Valid 5-step support-ticket DAG from spec §5."""
    return {
        "schema_version": 1,
        "name": "Support ticket triage",
        "inputs_schema": {
            "type": "object",
            "required": ["ticket_id", "body"],
            "properties": {
                "ticket_id": {"type": "string"},
                "body": {"type": "string", "maxLength": 4000},
            },
            "additionalProperties": False,
        },
        "start": "classify",
        "steps": [
            {
                "id": "classify",
                "type": "llm_classify",
                "config": {
                    "prompt_template_id": "ticket_classify",
                    "input": "{{ inputs.body }}",
                    "labels": ["billing", "bug", "other"],
                    "max_tokens": 100,
                },
                "next": "route",
            },
            {
                "id": "route",
                "type": "condition",
                "config": {
                    "branches": [
                        {
                            "when": {
                                "op": "eq",
                                "left": "{{ steps.classify.output.label }}",
                                "right": "billing",
                            },
                            "next": "approve",
                        }
                    ],
                    "else": "done",
                },
            },
            {
                "id": "approve",
                "type": "approval",
                "config": {
                    "assigned_role": "reviewer",
                    "expires_in_seconds": 86400,
                    "summary": "Create CRM ticket for {{ inputs.ticket_id }}",
                },
                "next": "crm",
            },
            {
                "id": "crm",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://crm.example.com/tickets",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"ticket_id": "{{ inputs.ticket_id }}"},
                    "timeout_seconds": 10,
                    "effect": "write",
                    "max_attempts": 3,
                },
                "next": "done",
            },
            {
                "id": "done",
                "type": "set_data",
                "config": {"values": {"status": "complete"}},
                "next": None,
            },
        ],
    }


def test_valid_dag_passes() -> None:
    """P3-T02: Valid 5-step support-ticket DAG from spec/00-global.md §5 passes with 0 issues."""
    wf = sample_support_ticket_definition()
    issues = validate_definition(wf, allowed_hosts={"crm.example.com"})
    assert len(issues) == 0, f"Expected 0 issues, got: {issues}"


def test_cycle_detection_self_loop_and_multi_node() -> None:
    """P3-T03: Direct self-loop (a -> a) and 3-node cycle return GRAPH_CYCLE."""
    # 1. Direct self-loop
    self_loop = {
        "schema_version": 1,
        "start": "step_a",
        "steps": [{"id": "step_a", "type": "set_data", "config": {"values": {}}, "next": "step_a"}],
    }
    issues = validate_definition(self_loop)
    cycle_issues = [i for i in issues if i.code == "GRAPH_CYCLE"]
    assert len(cycle_issues) >= 1
    assert "step_a" in cycle_issues[0].step_ids

    # 2. Multi-node cycle a -> b -> c -> a
    multi_cycle = {
        "schema_version": 1,
        "start": "step_a",
        "steps": [
            {"id": "step_a", "type": "set_data", "config": {"values": {}}, "next": "step_b"},
            {"id": "step_b", "type": "set_data", "config": {"values": {}}, "next": "step_c"},
            {"id": "step_c", "type": "set_data", "config": {"values": {}}, "next": "step_a"},
        ],
    }
    issues = validate_definition(multi_cycle)
    cycle_issues = [i for i in issues if i.code == "GRAPH_CYCLE"]
    assert len(cycle_issues) >= 1
    assert set(cycle_issues[0].step_ids) == {"step_a", "step_b", "step_c"}


def test_unreachable_step_detected() -> None:
    """P3-T04: Orphan step not reachable from start returns GRAPH_UNREACHABLE_STEP."""
    wf = {
        "schema_version": 1,
        "start": "step_a",
        "steps": [
            {"id": "step_a", "type": "set_data", "config": {"values": {}}, "next": None},
            {"id": "orphan", "type": "set_data", "config": {"values": {}}, "next": None},
        ],
    }
    issues = validate_definition(wf)
    unreachable = [i for i in issues if i.code == "GRAPH_UNREACHABLE_STEP"]
    assert len(unreachable) == 1
    assert "orphan" in unreachable[0].step_ids


def test_missing_step_reference() -> None:
    """P3-T05: next pointing to non-existent step returns GRAPH_MISSING_STEP."""
    wf = {
        "schema_version": 1,
        "start": "step_a",
        "steps": [
            {
                "id": "step_a",
                "type": "set_data",
                "config": {"values": {}},
                "next": "does_not_exist",
            },
        ],
    }
    issues = validate_definition(wf)
    missing = [i for i in issues if i.code == "GRAPH_MISSING_STEP"]
    assert len(missing) == 1
    assert "does_not_exist" in missing[0].message


def test_strict_dominator_template_ancestry() -> None:
    """P3-T06: Step referencing sibling branch step (not a strict dominator) returns UNKNOWN_REFERENCE."""
    # Diamond graph: start -> condition -> [branch_b, branch_c] -> join
    # join references steps.branch_b.output.val, which is NOT executed if branch_c is taken!
    wf = {
        "schema_version": 1,
        "start": "cond",
        "steps": [
            {
                "id": "cond",
                "type": "condition",
                "config": {
                    "branches": [{"when": {"op": "eq", "left": 1, "right": 1}, "next": "branch_b"}],
                    "else": "branch_c",
                },
            },
            {
                "id": "branch_b",
                "type": "set_data",
                "config": {"values": {"val_b": "data_b"}},
                "next": "join",
            },
            {
                "id": "branch_c",
                "type": "set_data",
                "config": {"values": {"val_c": "data_c"}},
                "next": "join",
            },
            {
                "id": "join",
                "type": "set_data",
                "config": {"values": {"result": "{{ steps.branch_b.output.val_b }}"}},
                "next": None,
            },
        ],
    }
    issues = validate_definition(wf)
    unknown_refs = [i for i in issues if i.code == "UNKNOWN_REFERENCE"]
    assert len(unknown_refs) >= 1
    assert any("does not dominate" in i.message for i in unknown_refs)


def test_missing_input_schema_property() -> None:
    """P3-T07: Step referencing {{ inputs.missing }} when additionalProperties=False returns UNKNOWN_REFERENCE."""
    wf = {
        "schema_version": 1,
        "inputs_schema": {
            "type": "object",
            "properties": {"known_field": {"type": "string"}},
            "additionalProperties": False,
        },
        "start": "step_a",
        "steps": [
            {
                "id": "step_a",
                "type": "set_data",
                "config": {"values": {"out": "{{ inputs.missing_field }}"}},
                "next": None,
            }
        ],
    }
    issues = validate_definition(wf)
    unknown_refs = [i for i in issues if i.code == "UNKNOWN_REFERENCE"]
    assert len(unknown_refs) >= 1
    assert "missing_field" in unknown_refs[0].message


def test_type_mismatch_classify_and_operators() -> None:
    """P3-T08: condition comparing llm_classify output to a label not in labels returns TYPE_MISMATCH."""
    wf = {
        "schema_version": 1,
        "start": "classify",
        "steps": [
            {
                "id": "classify",
                "type": "llm_classify",
                "config": {
                    "prompt_template_id": "tmpl",
                    "input": "test text",
                    "labels": ["spam", "ham"],
                },
                "next": "cond",
            },
            {
                "id": "cond",
                "type": "condition",
                "config": {
                    "branches": [
                        {
                            "when": {
                                "op": "eq",
                                "left": "{{ steps.classify.output.label }}",
                                "right": "invalid_label",
                            },
                            "next": None,
                        }
                    ],
                    "else": None,
                },
            },
        ],
    }
    issues = validate_definition(wf)
    mismatches = [i for i in issues if i.code == "TYPE_MISMATCH"]
    assert len(mismatches) >= 1
    assert "invalid_label" in mismatches[0].message


def test_forbidden_http_request_properties() -> None:
    """P3-T09: http_request with http:// URL or forbidden Authorization header returns FORBIDDEN_TOOL_PERMISSION."""
    wf = {
        "schema_version": 1,
        "start": "req",
        "steps": [
            {
                "id": "req",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "http://insecure.example.com/api",
                    "headers": {"Authorization": "Bearer leaked"},
                },
                "next": None,
            }
        ],
    }
    issues = validate_definition(wf)
    forbidden = [i for i in issues if i.code == "FORBIDDEN_TOOL_PERMISSION"]
    assert len(forbidden) >= 2  # Scheme error and forbidden header error


def test_irreversible_action_requires_approval() -> None:
    """P3-T10: Irreversible http_request without dominating approval step returns APPROVAL_REQUIRED_FOR_IRREVERSIBLE."""
    cred_id = uuid.uuid4()
    wf_no_approval = {
        "schema_version": 1,
        "start": "req",
        "steps": [
            {
                "id": "req",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.example.com/delete",
                    "credential_id": str(cred_id),
                    "effect": "write",
                },
                "next": None,
            }
        ],
    }

    # With irreversible scope on credential
    issues1 = validate_definition(
        wf_no_approval,
        allowed_hosts={"api.example.com"},
        credential_scopes={cred_id: {"irreversible"}},
    )
    assert any(i.code == "APPROVAL_REQUIRED_FOR_IRREVERSIBLE" for i in issues1)

    # Now add dominating approval step
    wf_with_approval = {
        "schema_version": 1,
        "start": "approve",
        "steps": [
            {
                "id": "approve",
                "type": "approval",
                "config": {"assigned_role": "admin", "summary": "Confirm irreversible operation"},
                "next": "req",
            },
            {
                "id": "req",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.example.com/delete",
                    "credential_id": str(cred_id),
                    "effect": "write",
                },
                "next": None,
            },
        ],
    }
    issues2 = validate_definition(
        wf_with_approval,
        allowed_hosts={"api.example.com"},
        credential_scopes={cred_id: {"irreversible"}},
    )
    assert not any(i.code == "APPROVAL_REQUIRED_FOR_IRREVERSIBLE" for i in issues2)
