# Phase 8 Spec: Evaluation Methodology and Observability

Learning material: `flowforge.md` → Phase 8. Contracts: `spec/00-global.md` (§3 `usage_records`; §8 API surface `/v1/organizations/{org_id}/usage` and `/metrics`; §9 OTel/metrics config; §11 observability services). **Prerequisite:** Phase 7 done-when is green.

## Scope
Frozen 30-case golden evaluation dataset (`evals/datasets/ticket_triage_v1.jsonl`), deterministic evaluation runner (`scripts/run_eval.py`) comparing prompt/model configurations (pass rate, per-label precision/recall, invalid-output rate, unsafe tool-call rate, p50/p95 latency, estimated cost), baseline evaluation report (`docs/evals/baseline-report.md`), end-to-end OpenTelemetry distributed tracing across API → Outbox → RabbitMQ → Celery worker → HTTP/LLM adapters, low-cardinality Prometheus metrics (`GET /metrics`), Grafana dashboard + Prometheus + Jaeger services in `compose.yaml`, `GET /v1/organizations/{org_id}/usage` endpoint, and frontend Usage & Cost dashboard page.

## Config additions (`Settings`)
`otel_exporter_otlp_endpoint: str = ""`, `otel_service_name: str = "flowforge-api"`, `metrics_enabled: bool = True`.

## Steps
| ID | Step | Done when |
|---|---|---|
| P8-S01 | Create `evals/datasets/ticket_triage_v1.jsonl` (30 frozen cases: 10 `billing`, 10 `bug`, 5 `other`, 5 adversarial prompt-injection tickets) + dataset checksum | file valid JSONL |
| P8-S02 | `app/evals/harness.py` and `scripts/run_eval.py`: runs the 30 cases against `FakeLLM` (baseline + drifted prompt variant) and optional `--live-sample N` against `OpenRouterClient`; writes `evals/results/baseline.json` and `docs/evals/baseline-report.md` | unit tests + script pass |
| P8-S03 | `app/observability/tracing.py`: OpenTelemetry `TracerProvider`, W3C `TraceContextTextMapPropagator` inject into `outbox_events.payload.trace_context` and RabbitMQ headers, extract in Celery worker (`parent_context`), child spans for each step, HTTP tool call, and LLM call | tracing tests (using `InMemorySpanExporter`) pass |
| P8-S04 | `app/observability/metrics.py`: Prometheus registry, HTTP middleware metrics, worker run/step/LLM counters and histograms, gauge collector for `flowforge_queue_lag_seconds`, `flowforge_oldest_queued_run_age_seconds`, and `flowforge_outbox_unpublished_count`; expose `GET /metrics` | metrics tests pass |
| P8-S05 | Extend `app/modules/usage/{schemas,repository,service,router}.py` with `GET /v1/organizations/{org_id}/usage?from=&to=` | integration tests pass |
| P8-S06 | Add `otel-collector`, `jaeger`, `prometheus`, and `grafana` (with provisioned `infra/observability/prometheus.yml` and `infra/observability/grafana-dashboard.json`) to `compose.yaml` | `docker compose config` valid |
| P8-S07 | Export `openapi.json`, run `gen:api`, build frontend `UsageDashboardPage` (`/orgs/:orgId/usage`) | Vitest tests pass |
| P8-S08 | Labs (evaluation drift comparison, queue-lag symptom detection, 6-step cross-process trace verification) + progress log | recorded in `docs/lab-notes/phase-08.md` |

## Files
```text
evals/datasets/ticket_triage_v1.jsonl
evals/results/baseline.json
app/evals/{__init__,harness}.py
scripts/run_eval.py
app/observability/{__init__,tracing,metrics}.py
app/modules/usage/{schemas,repository,service,router}.py        # modified / created
infra/observability/{otel-collector.yaml,prometheus.yml,grafana-datasources.yaml,grafana-dashboard.json}
tests/unit/{test_eval_harness,test_metrics_cardinality}.py
tests/integration/{test_tracing_propagation,test_usage_api,test_metrics_endpoint}.py
frontend/src/features/usage/UsageDashboardPage.tsx
docs/evals/baseline-report.md   docs/lab-notes/phase-08.md
```

## Observability & evaluation contracts

### 1. Golden Dataset & Evaluation Harness (`app/evals/harness.py`)
Each line in `evals/datasets/ticket_triage_v1.jsonl`:
```json
{"case_id": "TC-001", "ticket_id": "T-1001", "body": "Double charged on invoice #882", "expected_label": "billing", "expected_branch": "approve", "adversarial": false}
```
Metrics computed and stored in `evals/results/baseline.json`:
- `dataset_version`: `"v1"`, `dataset_sha256`: hex digest of the JSONL file.
- `total_cases`: `30`, `passed_cases`: int, `pass_rate`: float (`0.0–1.0`).
- `invalid_output_count`: int, `unsafe_tool_call_count`: int (must be `0`).
- `latency_ms_p50`, `latency_ms_p95`, `total_tokens`, `estimated_cost_micro_usd`.
- `per_case`: list of `{"case_id", "passed", "actual_label", "expected_label", "error_code"}`.

### 2. Distributed Trace Propagation (`app/observability/tracing.py`)
1. On `POST /v1/workflows/{id}/runs`: start span `api.trigger_run` (attributes: `flowforge.run_id`, `flowforge.workflow_id`). Inject current context via `TraceContextTextMapPropagator().inject(carrier)` and store `carrier` in `outbox_events.payload["trace_context"]`.
2. In `outbox_publisher`: extract `trace_context` from `event.payload`, create child span `outbox.publish`, and pass `trace_context` in the Celery task headers/kwargs.
3. In `runner.execute_run`: extract `trace_context` and start span `worker.execute_run(context=parent_ctx)` with `flowforge.run_id` and `flowforge.attempt_epoch`.
4. For each step attempt: start child span `worker.step.<step_type>` with `flowforge.step_id` and `flowforge.attempt_no`.
5. **Security rule:** never attach prompt bodies, request bodies, or credentials as span attributes.

### 3. Low-Cardinality Prometheus Metrics (`app/observability/metrics.py`)
Allowed label names across all metrics: `method`, `route_template` (e.g. `/v1/runs/{id}`, **never** the raw URL with UUIDs), `status_code`, `state`, `step_type`, `outcome`, `provider`, `model`.
**Forbidden labels:** `run_id`, `org_id`, `user_id`, `workflow_id`, `request_id` (enforced by unit test `P8-T02`).
Metrics defined:
- `flowforge_http_requests_total{method, route_template, status_code}` (Counter)
- `flowforge_http_request_duration_seconds{method, route_template}` (Histogram)
- `flowforge_runs_total{state}` (Counter of terminal transitions)
- `flowforge_step_attempts_total{step_type, status}` (Counter)
- `flowforge_llm_requests_total{provider, model, outcome}` (Counter)
- `flowforge_llm_tokens_total{provider, model, token_type}` (Counter, `token_type` in `prompt|completion`)
- `flowforge_oldest_queued_run_age_seconds` (Gauge: ` EXTRACT(EPOCH FROM (now() - MIN(created_at))) FROM workflow_runs WHERE state='QUEUED'`, `0` if none)
- `flowforge_outbox_unpublished_count` (Gauge: `SELECT count(*) FROM outbox_events WHERE published_at IS NULL`)

### 4. Usage API (`GET /v1/organizations/{org_id}/usage`)
Query parameters: `from` (ISO datetime, optional, default 30 days ago), `to` (ISO datetime, optional, default `now()`).
Response `200`:
```json
{
  "org_id": "uuid",
  "from": "2026-09-25T00:00:00Z",
  "to": "2026-10-25T23:59:59Z",
  "budget_limit_micro_usd": 5000000,
  "totals": {
    "llm_calls": 42,
    "prompt_tokens": 8400,
    "completion_tokens": 1260,
    "total_tokens": 9660,
    "estimated_cost_micro_usd": 19320,
    "billed_cost_micro_usd": 0
  },
  "by_model": [
    {"provider": "openrouter", "model_name": "openrouter/free", "calls": 42, "total_tokens": 9660, "estimated_cost_micro_usd": 19320, "billed_cost_micro_usd": 0}
  ],
  "runs_by_state": {"QUEUED": 0, "RUNNING": 1, "WAITING_APPROVAL": 2, "SUCCEEDED": 35, "FAILED": 3, "CANCELLED": 1}
}
```

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P8-T01 | test_eval_harness | `ticket_triage_v1.jsonl` has 30 valid cases; baseline evaluation reaches 100% pass rate and 0 unsafe tool calls on the reference `FakeLLM` rules; degraded prompt variant shows lower pass rate in diff report |
| P8-T02 | test_metrics_cardinality | Inspect all registered Prometheus metrics and after hitting `/v1/runs/{uuid}` confirm label values contain `/v1/runs/{id}` (route template) and never contain any UUID string |
| P8-T03 | test_tracing_propagation | Trigger a run → publish outbox → execute 3-step run with `InMemorySpanExporter` → all spans (`api.trigger_run`, `outbox.publish`, `worker.execute_run`, `worker.step.*`) share the exact same `trace_id` and form a connected parent-child tree |
| P8-T04 | test_metrics_endpoint | `GET /metrics` returns `200` with `flowforge_oldest_queued_run_age_seconds` and `flowforge_outbox_unpublished_count` reflecting live DB state |
| P8-T05 | test_usage_api | `GET /v1/organizations/{org_id}/usage` aggregates tokens, costs, and run state counts strictly for `org_id` within `[from, to]`; cross-tenant user gets `404`; `reviewer` role gets `403` (per spec §2 matrix) |

## Frontend
- `UsageDashboardPage` (`/orgs/:orgId/usage`): displays budget progress bar (`estimated_cost_micro_usd / budget_limit_micro_usd`), token totals, model breakdown table, and run outcomes summary (`SUCCEEDED`, `FAILED`, `WAITING_APPROVAL`, etc.).
- Frontend tests: `P8-F01` renders usage totals, budget bar, and model table; `P8-F02` handles empty usage state cleanly.

## Labs (`docs/lab-notes/phase-08.md`)
1. **Evaluation drift lab:** modify `ticket_classify.yaml` to weaken label instructions, re-run `python scripts/run_eval.py`, and record the pass-rate drop and confusion patterns against the frozen 30-case set.
2. **Stuck-queue symptom lab:** enqueue a run with the worker paused, wait 10 s, scrape `GET /metrics`, and show `flowforge_oldest_queued_run_age_seconds >= 10` while `GET /health` is still `200`.

## Verification commands
```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
python scripts/run_eval.py
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P8-T01…T05 and P8-F01…F02 pass.
- [ ] `docs/evals/baseline-report.md` and Labs 1–2 committed; Phase 8 PDF built.

## Agent brief
**Do:** use FastAPI `request.scope["route"].path` for the Prometheus `route_template` label. **Don't:** put `run_id`, `org_id`, or `user_id` into Prometheus labels or log raw prompts in OTel spans. **Stop and report** if OTel packages conflict with any pinned version in `requirements.txt`.
