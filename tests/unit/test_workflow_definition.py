"""Unit tests for canonical JSON serialization, checksum computation, and step models (P3-T01)."""

from __future__ import annotations

import hashlib

from app.domain.workflow_definition import canonical_json, definition_checksum, extract_placeholders


def test_canonical_json_and_checksum_stability() -> None:
    """P3-T01: Canonical JSON produces identical SHA-256 regardless of dict key insertion order."""
    def1 = {
        "schema_version": 1,
        "name": "Order Pipeline",
        "start": "step_a",
        "inputs_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["order_id"],
        },
        "steps": [
            {
                "id": "step_a",
                "type": "set_data",
                "config": {"values": {"k1": "v1", "k2": "v2"}},
                "next": None,
            }
        ],
    }

    # Different key insertion order at all levels
    def2 = {
        "steps": [
            {
                "next": None,
                "type": "set_data",
                "config": {"values": {"k2": "v2", "k1": "v1"}},
                "id": "step_a",
            }
        ],
        "name": "Order Pipeline",
        "inputs_schema": {
            "required": ["order_id"],
            "properties": {"amount": {"type": "number"}, "order_id": {"type": "string"}},
            "type": "object",
        },
        "start": "step_a",
        "schema_version": 1,
    }

    bytes1 = canonical_json(def1)
    bytes2 = canonical_json(def2)

    assert bytes1 == bytes2
    assert definition_checksum(def1) == definition_checksum(def2)
    assert hashlib.sha256(bytes1).hexdigest() == definition_checksum(def1)


def test_extract_placeholders() -> None:
    """Validate placeholder extraction from templates."""
    text = "Create ticket {{ inputs.ticket_id }} for user {{ steps.classify.output.label }}"
    assert extract_placeholders(text) == ["inputs.ticket_id", "steps.classify.output.label"]
