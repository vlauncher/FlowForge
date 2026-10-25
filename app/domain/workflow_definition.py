"""Domain models, canonical serialization, and checksums for workflow definitions."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Any, Literal
from uuid import UUID

import orjson
from pydantic import BaseModel, ConfigDict, Field

# Pattern for step identifier: lowercase alphanumeric + underscore, max 40 chars
STEP_ID_REGEX = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# Template placeholder pattern: {{ path }}
TEMPLATE_PLACEHOLDER_REGEX = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

# Reference pattern: inputs.<field> or steps.<step_id>.output.<field>
# or numeric array index like items.0.name
PATH_COMPONENT_REGEX = re.compile(r"^[a-zA-Z0-9_]+$")


def canonical_json(definition: dict[str, Any]) -> bytes:
    """Serialize workflow definition to canonical byte representation with sorted keys."""
    return orjson.dumps(definition, option=orjson.OPT_SORT_KEYS)


def definition_checksum(definition: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest of the canonical JSON representation."""
    return hashlib.sha256(canonical_json(definition)).hexdigest()


def extract_placeholders(text: str) -> list[str]:
    """Extract all template placeholder paths from a string (e.g. {{ field }})."""
    return [match.strip() for match in TEMPLATE_PLACEHOLDER_REGEX.findall(text)]


def extract_all_placeholders(val: Any) -> list[str]:
    """Recursively collect all template placeholders from nested structures."""
    placeholders: list[str] = []
    if isinstance(val, str):
        placeholders.extend(extract_placeholders(val))
    elif isinstance(val, dict):
        for k, v in val.items():
            if isinstance(k, str):
                placeholders.extend(extract_placeholders(k))
            placeholders.extend(extract_all_placeholders(v))
    elif isinstance(val, list):
        for item in val:
            placeholders.extend(extract_all_placeholders(item))
    return placeholders


# ---------------------------------------------------------------------------
# Step Config Models (Strict extra='forbid')
# ---------------------------------------------------------------------------


class SetDataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(description="Object of values or templates to resolve")


class ConditionWhen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "exists"]
    left: Any
    right: Any | None = None


class ConditionBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: ConditionWhen
    next: str | None = None


class ConditionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    branches: list[ConditionBranch] = Field(min_length=1, max_length=5)
    else_: str | None = Field(default=None, alias="else")


class HttpRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    url: str
    credential_id: UUID | str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    effect: Literal["read", "write"] | None = None
    max_attempts: int = Field(default=3, ge=1, le=5)
    provider_supports_idempotency: bool = True


class LlmClassifyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_template_id: str
    input: str
    labels: list[str] = Field(min_length=2, max_length=20)
    max_tokens: int = Field(default=100, ge=1, le=500)


class LlmTransformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_template_id: str
    input: str
    output_schema: dict[str, Any]
    max_tokens: int = Field(default=400, ge=1, le=1500)


class ApprovalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_role: Literal["reviewer", "admin", "owner"]
    summary: str
    expires_in_seconds: int = Field(default=86400, ge=60, le=604800)


# ---------------------------------------------------------------------------
# Step Definitions
# ---------------------------------------------------------------------------


class BaseStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    type: str


class SetDataStep(BaseStep):
    type: Literal["set_data"] = "set_data"
    config: SetDataConfig
    next: str | None = None


class ConditionStep(BaseStep):
    type: Literal["condition"] = "condition"
    config: ConditionConfig
    # Condition steps do not have top-level next; next transitions are in branches & else


class HttpRequestStep(BaseStep):
    type: Literal["http_request"] = "http_request"
    config: HttpRequestConfig
    next: str | None = None


class LlmClassifyStep(BaseStep):
    type: Literal["llm_classify"] = "llm_classify"
    config: LlmClassifyConfig
    next: str | None = None


class LlmTransformStep(BaseStep):
    type: Literal["llm_transform"] = "llm_transform"
    config: LlmTransformConfig
    next: str | None = None


class ApprovalStep(BaseStep):
    type: Literal["approval"] = "approval"
    config: ApprovalConfig
    next: str | None = None


StepUnion = Annotated[
    SetDataStep
    | ConditionStep
    | HttpRequestStep
    | LlmClassifyStep
    | LlmTransformStep
    | ApprovalStep,
    Field(discriminator="type"),
]


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str | None = None
    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    start: str
    steps: list[StepUnion] = Field(min_length=1, max_length=50)
