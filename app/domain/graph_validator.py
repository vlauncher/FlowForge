"""Deterministic DAG and workflow definition validator."""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import jsonschema
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError

from app.domain.workflow_definition import (
    STEP_ID_REGEX,
    ConditionStep,
    HttpRequestStep,
    LlmClassifyStep,
    LlmTransformStep,
    StepUnion,
    WorkflowDefinition,
    extract_all_placeholders,
)

FORBIDDEN_HEADERS = {"authorization", "cookie", "proxy-authorization", "host"}


@dataclass(frozen=True)
class ValidationIssue:
    """Represents a discrete validation issue found within a workflow definition."""

    code: str
    field: str
    message: str
    step_ids: list[str] = dataclasses.field(default_factory=list)


def compute_dominators(start_step: str, steps: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Compute dominators for all reachable steps starting from start_step."""
    adj: dict[str, list[str | None]] = {}
    for s in steps:
        sid = s.get("id")
        if not sid or not isinstance(sid, str):
            continue
        if s.get("type") == "condition":
            branches = s.get("config", {}).get("branches", [])
            b_nexts = [b.get("next") for b in branches if isinstance(b, dict)]
            else_next = s.get("config", {}).get("else")
            adj[sid] = [*b_nexts, else_next]
        else:
            adj[sid] = [s.get("next")]

    reachable: set[str] = set()
    queue = [start_step]
    while queue:
        curr = queue.pop(0)
        if curr in reachable:
            continue
        reachable.add(curr)
        for nxt in adj.get(curr, []):
            if nxt and nxt not in reachable:
                queue.append(nxt)

    preds: dict[str, set[str]] = {sid: set() for sid in reachable}
    for u in reachable:
        for v in adj.get(u, []):
            if v and v in reachable:
                preds[v].add(u)

    dom: dict[str, set[str]] = {}
    for sid in reachable:
        dom[sid] = {start_step} if sid == start_step else set(reachable)

    changed = True
    while changed:
        changed = False
        for sid in reachable:
            if sid == start_step:
                continue
            pred_set = preds[sid]
            new_dom = {sid} | (set.intersection(*(dom[p] for p in pred_set)) if pred_set else set())
            if new_dom != dom[sid]:
                dom[sid] = new_dom
                changed = True

    return dom


def _schema_depth(obj: Any, current_depth: int = 1) -> int:
    """Calculate maximum nesting depth of a JSON schema dictionary."""
    if not isinstance(obj, dict):
        return current_depth
    max_d = current_depth
    for v in obj.values():
        if isinstance(v, dict):
            max_d = max(max_d, _schema_depth(v, current_depth + 1))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    max_d = max(max_d, _schema_depth(item, current_depth + 1))
    return max_d


def validate_definition(
    raw: dict[str, Any],
    *,
    allowed_hosts: set[str] | None = None,
    credential_scopes: dict[uuid.UUID, set[str]] | None = None,
    known_prompt_templates: set[str] | None = None,
) -> list[ValidationIssue]:
    """Execute complete validation suite on workflow definition returning all discovered issues."""
    issues: list[ValidationIssue] = []

    if not isinstance(raw, dict):
        return [
            ValidationIssue(
                code="INVALID_STEP_CONFIG",
                field="definition",
                message="Definition must be a JSON object",
            )
        ]

    # ---------------------------------------------------------------------------
    # 1. Structural & Schema Checks (INVALID_STEP_CONFIG)
    # ---------------------------------------------------------------------------
    if raw.get("schema_version") != 1:
        issues.append(
            ValidationIssue(
                code="INVALID_STEP_CONFIG",
                field="schema_version",
                message="Workflow schema_version must be 1",
            )
        )

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 1 or len(raw_steps) > 50:
        issues.append(
            ValidationIssue(
                code="INVALID_STEP_CONFIG",
                field="steps",
                message="Workflow must declare between 1 and 50 steps",
            )
        )
        return issues

    # Validate inputs_schema if present
    inputs_schema = raw.get("inputs_schema", {})
    if inputs_schema:
        if not isinstance(inputs_schema, dict):
            issues.append(
                ValidationIssue(
                    code="INVALID_STEP_CONFIG",
                    field="inputs_schema",
                    message="inputs_schema must be an object",
                )
            )
        else:
            try:
                schema_bytes = json.dumps(inputs_schema).encode("utf-8")
                if len(schema_bytes) > 4096:
                    issues.append(
                        ValidationIssue(
                            code="INVALID_STEP_CONFIG",
                            field="inputs_schema",
                            message=(
                                f"inputs_schema size exceeds 4 KB limit ({len(schema_bytes)} bytes)"
                            ),
                        )
                    )
                if _schema_depth(inputs_schema) > 4:
                    issues.append(
                        ValidationIssue(
                            code="INVALID_STEP_CONFIG",
                            field="inputs_schema",
                            message="inputs_schema nesting depth exceeds maximum of 4",
                        )
                    )
                Draft202012Validator.check_schema(inputs_schema)
            except jsonschema.exceptions.SchemaError as err:
                issues.append(
                    ValidationIssue(
                        code="INVALID_STEP_CONFIG",
                        field="inputs_schema",
                        message=f"inputs_schema is not valid Draft 2020-12 schema: {err.message}",
                    )
                )

    # Validate step IDs and Pydantic parsing
    step_ids_seen: set[str] = set()
    parsed_steps: list[StepUnion] = []

    for idx, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            issues.append(
                ValidationIssue(
                    code="INVALID_STEP_CONFIG",
                    field=f"steps.{idx}",
                    message="Step must be a JSON object",
                )
            )
            continue

        step_id = s.get("id")
        if not isinstance(step_id, str) or not STEP_ID_REGEX.match(step_id):
            issues.append(
                ValidationIssue(
                    code="INVALID_STEP_CONFIG",
                    field=f"steps.{idx}.id",
                    message=f"Step ID '{step_id}' must match ^[a-z][a-z0-9_]{{0,39}}$",
                    step_ids=[str(step_id)] if step_id else [],
                )
            )
        elif step_id in step_ids_seen:
            issues.append(
                ValidationIssue(
                    code="INVALID_STEP_CONFIG",
                    field=f"steps.{idx}.id",
                    message=f"Duplicate step ID '{step_id}'",
                    step_ids=[step_id],
                )
            )
        else:
            step_ids_seen.add(step_id)

    # Parse full workflow via Pydantic model
    try:
        wf_model = WorkflowDefinition.model_validate(raw)
        parsed_steps = wf_model.steps
    except ValidationError as pydantic_err:
        for p_err in pydantic_err.errors():
            loc_parts = [str(p) for p in p_err["loc"]]
            loc_str = ".".join(loc_parts)
            s_ids: list[str] = []
            if len(loc_parts) >= 2 and loc_parts[0] == "steps" and loc_parts[1].isdigit():
                step_idx = int(loc_parts[1])
                if step_idx < len(raw_steps) and isinstance(raw_steps[step_idx], dict):
                    sid = raw_steps[step_idx].get("id")
                    if sid:
                        s_ids.append(str(sid))
            issues.append(
                ValidationIssue(
                    code="INVALID_STEP_CONFIG",
                    field=loc_str,
                    message=p_err["msg"],
                    step_ids=s_ids,
                )
            )

    # ---------------------------------------------------------------------------
    # 2. Missing Step References (GRAPH_MISSING_STEP)
    # ---------------------------------------------------------------------------
    start_step = raw.get("start")
    if not isinstance(start_step, str) or start_step not in step_ids_seen:
        issues.append(
            ValidationIssue(
                code="GRAPH_MISSING_STEP",
                field="start",
                message=f"Start step '{start_step}' does not exist in steps",
                step_ids=[str(start_step)] if start_step else [],
            )
        )

    # Build adjacency list
    adj: dict[str, list[str | None]] = {sid: [] for sid in step_ids_seen}

    for s in raw_steps:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or sid not in adj:
            continue

        stype = s.get("type")
        if stype == "condition":
            cfg = s.get("config", {})
            if isinstance(cfg, dict):
                branches = cfg.get("branches", [])
                if isinstance(branches, list):
                    for b_idx, b in enumerate(branches):
                        if isinstance(b, dict):
                            b_next = b.get("next")
                            if b_next is not None and b_next not in step_ids_seen:
                                issues.append(
                                    ValidationIssue(
                                        code="GRAPH_MISSING_STEP",
                                        field=f"steps.{sid}.config.branches.{b_idx}.next",
                                        message=(
                                            f"Branch transition references non-existent step '{b_next}'"
                                        ),
                                        step_ids=[sid, str(b_next)],
                                    )
                                )
                            adj[sid].append(b_next)
                else_next = cfg.get("else")
                if else_next is not None and else_next not in step_ids_seen:
                    issues.append(
                        ValidationIssue(
                            code="GRAPH_MISSING_STEP",
                            field=f"steps.{sid}.config.else",
                            message=(
                                f"Condition else transition references non-existent step '{else_next}'"
                            ),
                            step_ids=[sid, str(else_next)],
                        )
                    )
                adj[sid].append(else_next)
        else:
            nxt = s.get("next")
            if nxt is not None and nxt not in step_ids_seen:
                issues.append(
                    ValidationIssue(
                        code="GRAPH_MISSING_STEP",
                        field=f"steps.{sid}.next",
                        message=f"Step '{sid}' transition references non-existent step '{nxt}'",
                        step_ids=[sid, str(nxt)],
                    )
                )
            adj[sid].append(nxt)

    if not start_step or start_step not in step_ids_seen:
        return issues

    # ---------------------------------------------------------------------------
    # 3. Reachability Check (GRAPH_UNREACHABLE_STEP)
    # ---------------------------------------------------------------------------
    visited_reachable: set[str] = set()
    queue = [start_step]
    visited_reachable.add(start_step)

    while queue:
        curr = queue.pop(0)
        for target in adj.get(curr, []):
            if target is not None and target in step_ids_seen and target not in visited_reachable:
                visited_reachable.add(target)
                queue.append(target)

    unreachable = sorted(step_ids_seen - visited_reachable)
    if unreachable:
        issues.append(
            ValidationIssue(
                code="GRAPH_UNREACHABLE_STEP",
                field="steps",
                message=f"Steps not reachable from start '{start_step}': {', '.join(unreachable)}",
                step_ids=unreachable,
            )
        )

    # ---------------------------------------------------------------------------
    # 4. Cycle Detection & Termination (GRAPH_CYCLE)
    # ---------------------------------------------------------------------------
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(visited_reachable, WHITE)
    cycle_detected = False

    def dfs(u: str, path: list[str]) -> None:
        nonlocal cycle_detected
        color[u] = GRAY
        path.append(u)

        for v in adj.get(u, []):
            if v is None or v not in visited_reachable:
                continue
            if color[v] == GRAY:
                cycle_detected = True
                cycle_start_idx = path.index(v)
                cycle_nodes = path[cycle_start_idx:] + [v]
                cycle_path_str = " -> ".join(cycle_nodes)
                issues.append(
                    ValidationIssue(
                        code="GRAPH_CYCLE",
                        field="steps",
                        message=f"Workflow contains a directed cycle: {cycle_path_str}",
                        step_ids=list(dict.fromkeys(cycle_nodes)),
                    )
                )
            elif color[v] == WHITE:
                dfs(v, path)

        path.pop()
        color[u] = BLACK

    dfs(start_step, [])

    has_terminating_node = any(None in adj.get(sid, []) for sid in visited_reachable)
    if not has_terminating_node and not cycle_detected:
        issues.append(
            ValidationIssue(
                code="GRAPH_CYCLE",
                field="steps",
                message="Workflow has no terminating path (all paths must eventually reach null)",
                step_ids=list(visited_reachable),
            )
        )

    # ---------------------------------------------------------------------------
    # 5. Dominators & Ancestry for Template Placeholders (UNKNOWN_REFERENCE)
    # ---------------------------------------------------------------------------
    preds: dict[str, set[str]] = {sid: set() for sid in visited_reachable}
    for u in visited_reachable:
        for v in adj.get(u, []):
            if v is not None and v in visited_reachable:
                preds[v].add(u)

    dom: dict[str, set[str]] = {}
    for sid in visited_reachable:
        if sid == start_step:
            dom[sid] = {start_step}
        else:
            dom[sid] = set(visited_reachable)

    changed = True
    while changed:
        changed = False
        for sid in visited_reachable:
            if sid == start_step:
                continue
            pred_set = preds[sid]
            if not pred_set:
                new_dom = {sid}
            else:
                new_dom = {sid} | set.intersection(*(dom[p] for p in pred_set))
            if new_dom != dom[sid]:
                dom[sid] = new_dom
                changed = True

    steps_by_id: dict[str, StepUnion] = {s.id: s for s in parsed_steps}

    inputs_props = inputs_schema.get("properties", {}) if isinstance(inputs_schema, dict) else {}
    additional_props = (
        inputs_schema.get("additionalProperties", True) if isinstance(inputs_schema, dict) else True
    )

    for s in parsed_steps:
        if s.id not in visited_reachable:
            continue

        strict_dominators = dom.get(s.id, set()) - {s.id}
        cfg_dict = s.config.model_dump(by_alias=True)
        placeholders = extract_all_placeholders(cfg_dict)

        for ph in placeholders:
            parts = ph.split(".")
            if not parts:
                continue

            root = parts[0]
            if root == "inputs":
                if len(parts) < 2:
                    issues.append(
                        ValidationIssue(
                            code="UNKNOWN_REFERENCE",
                            field=f"steps.{s.id}.config",
                            message=f"Invalid placeholder '{{{{ {ph} }}}}': missing input field name",
                            step_ids=[s.id],
                        )
                    )
                elif additional_props is False and parts[1] not in inputs_props:
                    issues.append(
                        ValidationIssue(
                            code="UNKNOWN_REFERENCE",
                            field=f"steps.{s.id}.config",
                            message=(
                                f"Placeholder '{{{{ {ph} }}}}' references non-existent input '{parts[1]}'"
                            ),
                            step_ids=[s.id],
                        )
                    )
            elif root == "steps":
                if len(parts) < 3 or parts[2] != "output":
                    issues.append(
                        ValidationIssue(
                            code="UNKNOWN_REFERENCE",
                            field=f"steps.{s.id}.config",
                            message=(
                                f"Invalid placeholder '{{{{ {ph} }}}}': expected format 'steps.<id>.output.<field>'"
                            ),
                            step_ids=[s.id],
                        )
                    )
                else:
                    ref_id = parts[1]
                    if ref_id not in step_ids_seen:
                        issues.append(
                            ValidationIssue(
                                code="UNKNOWN_REFERENCE",
                                field=f"steps.{s.id}.config",
                                message=f"Placeholder '{{{{ {ph} }}}}' references unknown step '{ref_id}'",
                                step_ids=[s.id],
                            )
                        )
                    elif ref_id not in strict_dominators:
                        issues.append(
                            ValidationIssue(
                                code="UNKNOWN_REFERENCE",
                                field=f"steps.{s.id}.config",
                                message=(
                                    f"Placeholder '{{{{ {ph} }}}}' references step '{ref_id}' which does not dominate step '{s.id}'"
                                ),
                                step_ids=[s.id, ref_id],
                            )
                        )
            else:
                issues.append(
                    ValidationIssue(
                        code="UNKNOWN_REFERENCE",
                        field=f"steps.{s.id}.config",
                        message=f"Invalid placeholder root '{{{{ {ph} }}}}': must be 'inputs' or 'steps'",
                        step_ids=[s.id],
                    )
                )

    # ---------------------------------------------------------------------------
    # 6. Type Compatibility (TYPE_MISMATCH)
    # ---------------------------------------------------------------------------
    for s in parsed_steps:
        if isinstance(s, ConditionStep):
            for b_idx, b in enumerate(s.config.branches):
                left = b.when.left
                right = b.when.right
                op = b.when.op

                if isinstance(left, str):
                    ph_match = re.match(r"^\{\{\s*steps\.([a-z0-9_]+)\.output\.label\s*\}\}$", left)
                    if ph_match:
                        target_classify_id = ph_match.group(1)
                        target_step = steps_by_id.get(target_classify_id)
                        if isinstance(target_step, LlmClassifyStep):
                            valid_labels = set(target_step.config.labels)
                            if (
                                op in ("eq", "neq")
                                and isinstance(right, str)
                                and right not in valid_labels
                            ):
                                issues.append(
                                    ValidationIssue(
                                        code="TYPE_MISMATCH",
                                        field=f"steps.{s.id}.config.branches.{b_idx}.when.right",
                                        message=(
                                            f"Condition compares label to '{right}', but '{target_classify_id}' only defines labels: {sorted(valid_labels)}"
                                        ),
                                        step_ids=[s.id, target_classify_id],
                                    )
                                )

                if op in ("gt", "gte", "lt", "lte"):
                    if isinstance(right, str) and not right.startswith("{{"):
                        issues.append(
                            ValidationIssue(
                                code="TYPE_MISMATCH",
                                field=f"steps.{s.id}.config.branches.{b_idx}.when.right",
                                message=(
                                    f"Operator '{op}' cannot compare against string literal '{right}'"
                                ),
                                step_ids=[s.id],
                            )
                        )
                    if isinstance(left, str) and not left.startswith("{{"):
                        issues.append(
                            ValidationIssue(
                                code="TYPE_MISMATCH",
                                field=f"steps.{s.id}.config.branches.{b_idx}.when.left",
                                message=(f"Operator '{op}' cannot compare string literal '{left}'"),
                                step_ids=[s.id],
                            )
                        )

    # Check known prompt templates if provided
    if known_prompt_templates is not None:
        for s in parsed_steps:
            if isinstance(s, (LlmClassifyStep, LlmTransformStep)):
                pt_id = s.config.prompt_template_id
                if pt_id not in known_prompt_templates:
                    issues.append(
                        ValidationIssue(
                            code="INVALID_STEP_CONFIG",
                            field=f"steps.{s.id}.config.prompt_template_id",
                            message=f"Prompt template '{pt_id}' is unknown",
                            step_ids=[s.id],
                        )
                    )

    # ---------------------------------------------------------------------------
    # 7. Tool & Permission Policy (FORBIDDEN_TOOL_PERMISSION)
    # ---------------------------------------------------------------------------
    for s in parsed_steps:
        if isinstance(s, HttpRequestStep):
            cfg_http = s.config
            parsed_url = urlparse(cfg_http.url)

            if parsed_url.scheme != "https":
                issues.append(
                    ValidationIssue(
                        code="FORBIDDEN_TOOL_PERMISSION",
                        field=f"steps.{s.id}.config.url",
                        message=f"URL must use 'https://' scheme (got '{parsed_url.scheme}')",
                        step_ids=[s.id],
                    )
                )

            if parsed_url.username or parsed_url.password:
                issues.append(
                    ValidationIssue(
                        code="FORBIDDEN_TOOL_PERMISSION",
                        field=f"steps.{s.id}.config.url",
                        message="URL must not include username or password credentials",
                        step_ids=[s.id],
                    )
                )

            for header_name in cfg_http.headers.keys():
                if header_name.lower() in FORBIDDEN_HEADERS:
                    issues.append(
                        ValidationIssue(
                            code="FORBIDDEN_TOOL_PERMISSION",
                            field=f"steps.{s.id}.config.headers.{header_name}",
                            message=f"Header '{header_name}' is forbidden in http_request configuration",
                            step_ids=[s.id],
                        )
                    )

            if allowed_hosts is not None and parsed_url.hostname:
                if parsed_url.hostname not in allowed_hosts:
                    issues.append(
                        ValidationIssue(
                            code="FORBIDDEN_TOOL_PERMISSION",
                            field=f"steps.{s.id}.config.url",
                            message=f"Host '{parsed_url.hostname}' is not in allowed egress hosts",
                            step_ids=[s.id],
                        )
                    )

    # ---------------------------------------------------------------------------
    # 8. Irreversible Tool Gate (APPROVAL_REQUIRED_FOR_IRREVERSIBLE)
    # ---------------------------------------------------------------------------
    for s in parsed_steps:
        if isinstance(s, HttpRequestStep):
            effect = s.config.effect or ("read" if s.config.method == "GET" else "write")
            cred_id = s.config.credential_id
            is_irreversible = False

            if effect == "write":
                if cred_id and credential_scopes:
                    try:
                        c_uuid = uuid.UUID(str(cred_id))
                        scopes = credential_scopes.get(c_uuid, set())
                        if "irreversible" in scopes:
                            is_irreversible = True
                    except ValueError:
                        pass
                elif not cred_id:
                    is_irreversible = True

            if is_irreversible:
                strict_doms = dom.get(s.id, set()) - {s.id}
                has_dominating_approval = any(
                    s_id in strict_doms
                    and s_id in steps_by_id
                    and getattr(steps_by_id[s_id], "type", None) == "approval"
                    for s_id in strict_doms
                )
                if not has_dominating_approval:
                    issues.append(
                        ValidationIssue(
                            code="APPROVAL_REQUIRED_FOR_IRREVERSIBLE",
                            field=f"steps.{s.id}",
                            message=(
                                f"Irreversible write operation in step '{s.id}' requires an approval step dominating it"
                            ),
                            step_ids=[s.id],
                        )
                    )

    return issues
