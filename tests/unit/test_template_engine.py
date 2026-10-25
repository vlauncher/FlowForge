"""Unit tests for the Template Engine (P4-T02)."""

import pytest

from app.domain.template_engine import (
    TemplateResolutionError,
    build_scope,
    evaluate_condition,
    evaluate_op,
    resolve_value,
)
from app.domain.workflow_definition import ConditionBranch, ConditionConfig, ConditionWhen


def test_single_placeholder_type_preservation() -> None:
    inputs = {
        "count": 42,
        "is_active": True,
        "payload": {"key": "val", "arr": [1, 2, 3]},
        "ratio": 3.14,
    }
    context = {
        "step_1": {"nested_num": 100, "flag": False},
    }
    scope = build_scope(inputs, context)

    # Int preserved
    res_int = resolve_value("{{ inputs.count }}", scope)
    assert res_int == 42
    assert isinstance(res_int, int)

    # Bool preserved
    res_bool = resolve_value("{{ inputs.is_active }}", scope)
    assert res_bool is True
    assert isinstance(res_bool, bool)

    # Dict preserved
    res_dict = resolve_value("{{ inputs.payload }}", scope)
    assert res_dict == {"key": "val", "arr": [1, 2, 3]}
    assert isinstance(res_dict, dict)

    # Float preserved
    res_float = resolve_value("{{ inputs.ratio }}", scope)
    assert res_float == 3.14
    assert isinstance(res_float, float)

    # Step output preserved
    res_step = resolve_value("{{ steps.step_1.output.nested_num }}", scope)
    assert res_step == 100
    assert isinstance(res_step, int)


def test_mixed_string_interpolation() -> None:
    inputs = {"name": "Alice", "ticket_id": "T-1234"}
    context = {"classify": {"label": "billing"}}
    scope = build_scope(inputs, context)

    template = "Ticket {{ inputs.ticket_id }} for {{ inputs.name }} classified as {{ steps.classify.output.label }}"
    result = resolve_value(template, scope)
    assert result == "Ticket T-1234 for Alice classified as billing"


def test_recursive_data_structure_resolution() -> None:
    inputs = {"user": "Bob", "code": 7}
    scope = build_scope(inputs, {})

    nested = {
        "user_name": "{{ inputs.user }}",
        "details": {
            "num": "{{ inputs.code }}",
            "tags": ["item-{{ inputs.code }}", "{{ inputs.user }}"],
        },
    }
    resolved = resolve_value(nested, scope)
    assert resolved == {
        "user_name": "Bob",
        "details": {
            "num": 7,
            "tags": ["item-7", "Bob"],
        },
    }


def test_missing_field_raises_error() -> None:
    scope = build_scope({"a": 1}, {})
    with pytest.raises(TemplateResolutionError):
        resolve_value("{{ inputs.missing }}", scope)
    with pytest.raises(TemplateResolutionError):
        resolve_value("{{ steps.nonexistent.output }}", scope)


def test_condition_operators() -> None:
    assert evaluate_op("eq", 10, 10) is True
    assert evaluate_op("eq", 10, 20) is False
    assert evaluate_op("neq", "a", "b") is True
    assert evaluate_op("gt", 5, 3) is True
    assert evaluate_op("gt", 3, 5) is False
    assert evaluate_op("gte", 5, 5) is True
    assert evaluate_op("lt", 2, 8) is True
    assert evaluate_op("lte", 8, 8) is True
    assert evaluate_op("in", "cat", ["dog", "cat", "fish"]) is True
    assert evaluate_op("in", "cat", "concatenation") is True
    assert evaluate_op("in", "lion", ["dog", "cat"]) is False
    assert evaluate_op("exists", "something", True) is True
    assert evaluate_op("exists", None, True) is False
    assert evaluate_op("exists", "", True) is False


def test_evaluate_condition_branches() -> None:
    config = ConditionConfig(
        branches=[
            ConditionBranch(
                when=ConditionWhen(
                    op="eq", left="{{ steps.classify.output.label }}", right="billing"
                ),
                next="handle_billing",
            ),
            ConditionBranch(
                when=ConditionWhen(op="gt", left="{{ inputs.priority }}", right=3),
                next="handle_high_priority",
            ),
        ],
        else_="handle_default",
    )

    # Branch 1 matches
    next_step = evaluate_condition(
        config,
        inputs={"priority": 1},
        context={"classify": {"label": "billing"}},
    )
    assert next_step == "handle_billing"

    # Branch 2 matches
    next_step = evaluate_condition(
        config,
        inputs={"priority": 5},
        context={"classify": {"label": "tech_support"}},
    )
    assert next_step == "handle_high_priority"

    # Else branch matches
    next_step = evaluate_condition(
        config,
        inputs={"priority": 2},
        context={"classify": {"label": "other"}},
    )
    assert next_step == "handle_default"
