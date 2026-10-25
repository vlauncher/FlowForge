"""Template Engine (pure domain, zero framework or DB dependencies).

Resolves template expressions (e.g. {{ inputs.x }}, {{ steps.step_id.output.y }})
and evaluates condition branch operators.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.workflow_definition import ConditionConfig

SINGLE_PLACEHOLDER_REGEX = re.compile(r"^\s*\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}\s*$")
ANY_PLACEHOLDER_REGEX = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class TemplateResolutionError(Exception):
    """Raised when a placeholder cannot be resolved from scope."""


def _get_by_path(root: dict[str, Any], path: str) -> Any:
    """Traverse a dotted path in a nested dictionary/object."""
    parts = path.split(".")
    curr: Any = root
    for _idx, part in enumerate(parts):
        if curr is None:
            raise TemplateResolutionError(
                f"Cannot access property '{part}' of None (path: '{path}')"
            )
        if isinstance(curr, dict):
            if part not in curr:
                raise TemplateResolutionError(f"Key '{part}' not found in scope (path: '{path}')")
            curr = curr[part]
        elif isinstance(curr, (list, tuple)):
            try:
                elem_idx = int(part)
                curr = curr[elem_idx]
            except (ValueError, IndexError):
                raise TemplateResolutionError(
                    f"Index '{part}' invalid or out of range for list (path: '{path}')"
                ) from None
        elif hasattr(curr, part):
            curr = getattr(curr, part)
        else:
            raise TemplateResolutionError(
                f"Attribute '{part}' not found on {type(curr).__name__} (path: '{path}')"
            )
    return curr


def build_scope(inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Construct the unified evaluation root from inputs and context."""
    steps_scope: dict[str, Any] = {}
    for step_id, step_output in context.items():
        entry: dict[str, Any] = {"output": step_output}
        if isinstance(step_output, dict):
            for k, v in step_output.items():
                if k not in entry:
                    entry[k] = v
        steps_scope[step_id] = entry
    return {
        "inputs": inputs,
        "steps": steps_scope,
    }


def resolve_value(val: Any, scope: dict[str, Any]) -> Any:
    """Recursively resolve templates within arbitrary data structures.

    - If val is a string matching strictly '{{ path }}', returns the resolved object
      preserving original Python type (int, bool, dict, list, etc.).
    - If val is a string with mixed text/placeholders, returns the interpolated string.
    - If val is dict/list, resolves all children recursively.
    - Otherwise returns val unchanged.
    """
    if isinstance(val, str):
        # 1. Single placeholder check: preserves type
        single_match = SINGLE_PLACEHOLDER_REGEX.match(val)
        if single_match:
            path = single_match.group(1)
            return _get_by_path(scope, path)

        # 2. String interpolation check
        if "{{" in val:

            def _replace(match: re.Match[str]) -> str:
                path = match.group(1)
                resolved = _get_by_path(scope, path)
                if resolved is None:
                    return ""
                return str(resolved)

            return ANY_PLACEHOLDER_REGEX.sub(_replace, val)

        return val

    if isinstance(val, dict):
        return {k: resolve_value(v, scope) for k, v in val.items()}

    if isinstance(val, list):
        return [resolve_value(item, scope) for item in val]

    return val


def evaluate_op(op: str, left: Any, right: Any) -> bool:
    """Evaluate a comparison operator on two values."""
    if op == "eq":
        return bool(left == right)
    if op == "neq":
        return bool(left != right)
    if op == "gt":
        try:
            return bool(left > right)
        except TypeError:
            return False
    if op == "gte":
        try:
            return bool(left >= right)
        except TypeError:
            return False
    if op == "lt":
        try:
            return bool(left < right)
        except TypeError:
            return False
    if op == "lte":
        try:
            return bool(left <= right)
        except TypeError:
            return False
    if op == "in":
        try:
            return bool(left in right)
        except TypeError:
            return False
    if op == "exists":
        if right is False:
            return left is None or left == ""
        return left is not None and left != ""
    raise ValueError(f"Unsupported condition operator: '{op}'")


def evaluate_condition(
    config: ConditionConfig, inputs: dict[str, Any], context: dict[str, Any]
) -> str | None:
    """Evaluate branches of a ConditionStep and return the target next step id."""
    scope = build_scope(inputs, context)
    for branch in config.branches:
        resolved_left = resolve_value(branch.when.left, scope)
        resolved_right = resolve_value(branch.when.right, scope)
        if evaluate_op(branch.when.op, resolved_left, resolved_right):
            return branch.next
    return config.else_
