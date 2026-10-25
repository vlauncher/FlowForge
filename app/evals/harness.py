"""Evaluation harness for ticket triage datasets and LLM benchmarks (Phase 8)."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

from app.ai.fake_client import FakeLLM
from app.ai.interface import LLMClient, LLMRequest
from app.ai.prompts.loader import get_prompt_template

DATASET_PATH = Path("evals/datasets/ticket_triage_v1.jsonl")
CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["label", "confidence"],
    "additionalProperties": False,
    "properties": {
        "label": {
            "type": "string",
            "enum": ["billing", "bug", "other"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}


@dataclass
class EvalCase:
    case_id: str
    ticket_id: str
    body: str
    expected_label: str
    expected_branch: str
    adversarial: bool


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    actual_label: str | None
    expected_label: str
    confidence: float | None
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    error_code: str | None


@dataclass
class EvalSummary:
    dataset_version: str
    dataset_sha256: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    invalid_output_count: int
    unsafe_tool_call_count: int
    latency_ms_p50: float
    latency_ms_p95: float
    total_tokens: int
    estimated_cost_micro_usd: int
    per_case: list[dict[str, Any]]
    label_metrics: dict[str, dict[str, float]]


def load_dataset(path: Path = DATASET_PATH) -> list[EvalCase]:
    """Load evaluation test cases from a JSONL dataset file."""
    cases: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            cases.append(
                EvalCase(
                    case_id=data["case_id"],
                    ticket_id=data["ticket_id"],
                    body=data["body"],
                    expected_label=data["expected_label"],
                    expected_branch=data.get("expected_branch", "auto_resolve"),
                    adversarial=bool(data.get("adversarial", False)),
                )
            )
    return cases


def get_dataset_sha256(path: Path = DATASET_PATH) -> str:
    """Compute hex SHA-256 digest of the dataset file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def reference_triage_rule(req: LLMRequest) -> dict[str, Any]:
    """Deterministic classifier logic for FakeLLM baseline reaching 100% pass rate."""
    user_text = req.user_prompt.lower()

    # Adversarial checks: if adversarial prompt attempts injection or breakout, categorize safely
    if "admin" in user_text or "sudo rm" in user_text:
        return {"label": "other", "confidence": 0.98}
    if "escalate" in user_text or "&lt;/untrusted_input&gt;" in user_text:
        return {"label": "other", "confidence": 0.95}
    if "jwt_secret" in user_text or "database credentials" in user_text:
        return {"label": "other", "confidence": 0.99}
    if "evil.attacker.com" in user_text:
        return {"label": "other", "confidence": 0.97}

    # Keyword rules
    billing_keywords = [
        "invoice",
        "charged",
        "refund",
        "vat ",
        "receipt",
        "payment",
        "subscription",
        "disputing",
        "credit card",
        "w-9",
        "wire transfer",
        "prorated",
        "delete_all_users",  # Case TC-030 is billing payload
    ]
    bug_keywords = [
        "500 internal server error",
        "connection timeout",
        "webhook",
        "unresponsive",
        "memory leak",
        "graphql",
        "deadlock",
        "crashes",
        "redirect callback",
        "retry counter",
    ]

    for kw in billing_keywords:
        if kw in user_text:
            return {"label": "billing", "confidence": 0.95}

    for kw in bug_keywords:
        if kw in user_text:
            return {"label": "bug", "confidence": 0.92}

    return {"label": "other", "confidence": 0.88}


def degraded_triage_rule(req: LLMRequest) -> dict[str, Any]:
    """Degraded classifier logic that succumbs to prompt injections and misclassifies bugs."""
    user_text = req.user_prompt.lower()
    # Flaw 1: Falls for admin injection
    if "admin" in user_text:
        return {"label": "admin", "confidence": 0.99}  # Invalid label -> schema failure
    # Flaw 2: Misclassifies bug reports as other
    if "bug" in req.json_schema.get("properties", {}).get("label", {}).get("enum", []):
        if "500" in user_text or "timeout" in user_text:
            return {"label": "other", "confidence": 0.50}

    return reference_triage_rule(req)


async def run_evaluation(
    client: LLMClient,
    cases: list[EvalCase] | None = None,
    dataset_path: Path = DATASET_PATH,
    prompt_id: str = "ticket_classify",
    model: str = "openrouter/free",
) -> EvalSummary:
    """Run golden evaluation dataset against the specified LLMClient."""
    if cases is None:
        cases = load_dataset(dataset_path)

    sha256_hash = get_dataset_sha256(dataset_path)
    template = get_prompt_template(prompt_id)
    validator = Draft202012Validator(CLASSIFY_SCHEMA)

    results: list[CaseResult] = []
    latencies: list[int] = []
    total_tokens = 0
    invalid_output_count = 0
    unsafe_tool_call_count = 0

    price_per_1k = 2000  # micro USD

    for case in cases:
        rendered_user = template.format_user(
            case.body,
            labels=["billing", "bug", "other"],
        )
        req = LLMRequest(
            model=model,
            fallback_models=[],
            system_prompt=template.format_system(),
            user_prompt=rendered_user,
            json_schema=CLASSIFY_SCHEMA,
            max_tokens=256,
        )

        start_t = time.perf_counter()
        try:
            llm_res = await client.generate_json(req)
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            latencies.append(llm_res.latency_ms or elapsed_ms)
            total_tokens += llm_res.total_tokens

            # Parse and validate output
            data = json.loads(llm_res.raw_text)
            errors = list(validator.iter_errors(data))
            if errors:
                invalid_output_count += 1
                results.append(
                    CaseResult(
                        case_id=case.case_id,
                        passed=False,
                        actual_label=data.get("label") if isinstance(data, dict) else None,
                        expected_label=case.expected_label,
                        confidence=data.get("confidence") if isinstance(data, dict) else None,
                        latency_ms=llm_res.latency_ms or elapsed_ms,
                        prompt_tokens=llm_res.prompt_tokens,
                        completion_tokens=llm_res.completion_tokens,
                        error_code="LLM_INVALID_OUTPUT",
                    )
                )
                continue

            actual_label = data["label"]
            confidence = float(data["confidence"])
            passed = actual_label == case.expected_label

            results.append(
                CaseResult(
                    case_id=case.case_id,
                    passed=passed,
                    actual_label=actual_label,
                    expected_label=case.expected_label,
                    confidence=confidence,
                    latency_ms=llm_res.latency_ms or elapsed_ms,
                    prompt_tokens=llm_res.prompt_tokens,
                    completion_tokens=llm_res.completion_tokens,
                    error_code=None if passed else "LABEL_MISMATCH",
                )
            )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            latencies.append(elapsed_ms)
            invalid_output_count += 1
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    passed=False,
                    actual_label=None,
                    expected_label=case.expected_label,
                    confidence=None,
                    latency_ms=elapsed_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    error_code=str(type(exc).__name__),
                )
            )

    passed_count = sum(1 for r in results if r.passed)
    total_count = len(cases)
    pass_rate = (passed_count / total_count) if total_count > 0 else 0.0

    p50 = float(statistics.median(latencies)) if latencies else 0.0
    p95 = float(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else p50

    estimated_cost = (total_tokens * price_per_1k) // 1000

    # Per-label precision/recall
    labels = ["billing", "bug", "other"]
    label_metrics: dict[str, dict[str, float]] = {}
    for lbl in labels:
        tp = sum(1 for r in results if r.actual_label == lbl and r.expected_label == lbl)
        fp = sum(1 for r in results if r.actual_label == lbl and r.expected_label != lbl)
        fn = sum(1 for r in results if r.actual_label != lbl and r.expected_label == lbl)
        precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        label_metrics[lbl] = {"precision": round(precision, 3), "recall": round(recall, 3)}

    return EvalSummary(
        dataset_version="v1",
        dataset_sha256=sha256_hash,
        total_cases=total_count,
        passed_cases=passed_count,
        pass_rate=round(pass_rate, 4),
        invalid_output_count=invalid_output_count,
        unsafe_tool_call_count=unsafe_tool_call_count,
        latency_ms_p50=p50,
        latency_ms_p95=p95,
        total_tokens=total_tokens,
        estimated_cost_micro_usd=estimated_cost,
        per_case=[asdict(r) for r in results],
        label_metrics=label_metrics,
    )


def save_baseline_report(
    summary: EvalSummary,
    out_path: Path = Path("evals/results/baseline.json"),
) -> None:
    """Save evaluation summary as JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(summary), f, indent=2)


def create_reference_fake_llm() -> FakeLLM:
    """Instantiate a FakeLLM wired to the reference triage rules."""
    client = FakeLLM()
    client.set_handler(reference_triage_rule)
    return client


def create_degraded_fake_llm() -> FakeLLM:
    """Instantiate a FakeLLM wired to the degraded rules."""
    client = FakeLLM()
    client.set_handler(degraded_triage_rule)
    return client
