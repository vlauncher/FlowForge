"""Structured output parsing and validation against JSON schemas."""

from __future__ import annotations

from typing import Any

import jsonschema
import orjson

from app.ai.interface import InvalidLLMOutputError


def strip_code_fences(text: str) -> str:
    """Strip optional markdown ```json ... ``` or ``` ... ``` fences from raw LLM output."""
    s = text.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def parse_and_validate_json(raw_text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON string (stripping markdown fences) and validate against Draft202012 schema.

    Raises InvalidLLMOutputError if parsing fails or schema validation fails.
    """
    cleaned = strip_code_fences(raw_text)
    if not cleaned:
        raise InvalidLLMOutputError("Empty LLM output")

    try:
        data = orjson.loads(cleaned)
    except Exception as e:
        raise InvalidLLMOutputError(f"Malformed JSON: {e}") from e

    if not isinstance(data, dict):
        raise InvalidLLMOutputError(f"Expected JSON object, got {type(data).__name__}")

    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        formatted = []
        for err in errors:
            loc = ".".join(str(p) for p in err.absolute_path) or "root"
            formatted.append({"field": loc, "message": err.message})
        raise InvalidLLMOutputError(
            f"Schema validation failed with {len(errors)} error(s)",
            errors=formatted,
        )

    return data
