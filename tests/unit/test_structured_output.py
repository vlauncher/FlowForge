"""Unit tests for structured output JSON schema parsing and validation (P6-T03)."""

from __future__ import annotations

import pytest

from app.ai.interface import InvalidLLMOutputError
from app.ai.validator import parse_and_validate_json, strip_code_fences

CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["label", "confidence"],
    "properties": {
        "label": {"type": "string", "enum": ["billing", "bug", "feature", "other"]},
        "confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}


def test_strip_code_fences() -> None:
    """Markdown fences must be stripped cleanly."""
    assert strip_code_fences('```json\n{"hello": "world"}\n```') == '{"hello": "world"}'
    assert strip_code_fences('```\n{"hello": "world"}\n```') == '{"hello": "world"}'
    assert strip_code_fences('{"hello": "world"}') == '{"hello": "world"}'


def test_valid_json_and_fenced_json_pass_validation() -> None:
    """Valid JSON conforming to schema passes validation."""
    raw = '{"label": "billing", "confidence": 0.98}'
    result = parse_and_validate_json(raw, CLASSIFY_SCHEMA)
    assert result == {"label": "billing", "confidence": 0.98}

    fenced = '```json\n{"label": "bug", "confidence": 0.85}\n```'
    result2 = parse_and_validate_json(fenced, CLASSIFY_SCHEMA)
    assert result2 == {"label": "bug", "confidence": 0.85}

    null_confidence = '{"label": "other", "confidence": null}'
    result3 = parse_and_validate_json(null_confidence, CLASSIFY_SCHEMA)
    assert result3 == {"label": "other", "confidence": None}


def test_invalid_json_syntax_fails() -> None:
    """Malformed non-JSON strings raise InvalidLLMOutputError."""
    with pytest.raises(InvalidLLMOutputError, match="Malformed JSON"):
        parse_and_validate_json("I think the label is billing.", CLASSIFY_SCHEMA)

    with pytest.raises(InvalidLLMOutputError, match="Empty LLM output"):
        parse_and_validate_json("   ", CLASSIFY_SCHEMA)


def test_missing_required_field_fails() -> None:
    """Missing required field raises InvalidLLMOutputError."""
    raw = '{"label": "billing"}'
    with pytest.raises(InvalidLLMOutputError) as exc_info:
        parse_and_validate_json(raw, CLASSIFY_SCHEMA)
    assert exc_info.value.code == "LLM_INVALID_OUTPUT"
    assert any("confidence" in str(e) for e in (exc_info.value.errors or []))


def test_additional_property_fails() -> None:
    """Enforcing additionalProperties=False rejects injected keys."""
    raw = '{"label": "billing", "confidence": 0.9, "admin_access": true}'
    with pytest.raises(InvalidLLMOutputError) as exc_info:
        parse_and_validate_json(raw, CLASSIFY_SCHEMA)
    assert exc_info.value.code == "LLM_INVALID_OUTPUT"
    assert any("admin_access" in str(e) for e in (exc_info.value.errors or []))


def test_enum_mismatch_fails() -> None:
    """Values not in allowed enum list raise InvalidLLMOutputError."""
    raw = '{"label": "hacked_label", "confidence": 0.9}'
    with pytest.raises(InvalidLLMOutputError) as exc_info:
        parse_and_validate_json(raw, CLASSIFY_SCHEMA)
    assert exc_info.value.code == "LLM_INVALID_OUTPUT"
    assert any("hacked_label" in str(e) for e in (exc_info.value.errors or []))
