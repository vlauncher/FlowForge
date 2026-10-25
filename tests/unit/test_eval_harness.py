"""Unit tests for evaluation harness and golden dataset (P8-T01)."""

from __future__ import annotations

import pytest

from app.evals.harness import (
    create_degraded_fake_llm,
    create_reference_fake_llm,
    get_dataset_sha256,
    load_dataset,
    run_evaluation,
)


@pytest.mark.asyncio
async def test_eval_harness_baseline_and_drift() -> None:
    """P8-T01: ticket_triage_v1.jsonl has 30 valid cases; reference FakeLLM reaches 100%; degraded drops."""
    cases = load_dataset()
    assert len(cases) == 30, f"Expected exactly 30 frozen cases, got {len(cases)}"

    # Check sha256 checksum is present and valid
    checksum = get_dataset_sha256()
    assert len(checksum) == 64
    assert int(checksum, 16) > 0

    # Ensure required label distributions
    billing_count = sum(1 for c in cases if c.expected_label == "billing")
    bug_count = sum(1 for c in cases if c.expected_label == "bug")
    other_count = sum(1 for c in cases if c.expected_label == "other")
    adversarial_count = sum(1 for c in cases if c.adversarial)

    assert billing_count >= 10
    assert bug_count >= 10
    assert other_count >= 5
    assert adversarial_count == 5

    # 1. Reference baseline run
    ref_client = create_reference_fake_llm()
    baseline = await run_evaluation(ref_client, cases)

    assert baseline.total_cases == 30
    assert baseline.passed_cases == 30
    assert baseline.pass_rate == 1.0
    assert baseline.invalid_output_count == 0
    assert baseline.unsafe_tool_call_count == 0

    # 2. Degraded variant run
    degraded_client = create_degraded_fake_llm()
    drift = await run_evaluation(degraded_client, cases)

    assert drift.pass_rate < baseline.pass_rate
    assert drift.invalid_output_count >= 1
