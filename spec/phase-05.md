# Phase 5 Spec: Reliability, HTTP Tool Adapter, and Recovery

Learning material: `flowforge.md` → Phase 5. Contracts: `spec/00-global.md` (§3 tables `integration_credentials`, `tool_effects`; §4 state machines R3, R7, R9–R11; §5 `http_request` step; §6 worker retry/backoff/sweeper parameters; §7 errors; §8 API surface). **Prerequisite:** Phase 4 done-when is green.

## Scope
Migration `0004_tools_credentials`, credential storage (AES-256-GCM encrypted at rest, write-only API), allowlisted HTTP tool adapter (`http_request` step) with `tool_effects` ledger (`INTENDED → COMMITTED | FAILED | AMBIGUOUS`), exponential backoff with full jitter and `Retry-After` handling, per-provider circuit breaker, recovery sweeper for stale `RUNNING` leases and delayed retries, `POST /v1/runs/{id}/cancel`, `POST /v1/runs/{id}/retry`, and frontend credentials page + step retry/error timeline + cancel/retry actions.

## Config additions (`Settings`)
`egress_allowed_hosts: list[str] = []`, `egress_block_private: bool = True`, `secrets_master_keys: str` (`key_id:base64_32_byte_key` comma-separated; default dev key in `.env.example`, required in `prod`).

## Steps
| ID | Step | Done when |
|---|---|---|
| P5-S01 | `app/core/crypto.py`: AES-256-GCM encrypt/decrypt with `key_id` support | unit tests pass |
| P5-S02 | Revision `0004_tools_credentials` (`integration_credentials`, `tool_effects`) | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds |
| P5-S03 | `app/modules/integrations/{models,schemas,repository,service,router}.py`: create/list credentials (never return secret) | integration tests pass |
| P5-S04 | `app/infrastructure/http_tool/{backoff,circuit_breaker,adapter}.py`: allowlist check, timeout, 64 KB response cap, `Idempotency-Key` header injection, `tool_effects` ledger protocol | unit + integration tests pass |
| P5-S05 | Extend `app/workers/runner.py` with `http_request` step, bounded retries (`next_attempt_at`), and `AMBIGUOUS` effect halt; add `app/workers/sweeper.py` to `scheduler.py` | worker retry + crash recovery tests pass |
| P5-S06 | Add `POST /v1/runs/{id}/cancel` and `POST /v1/runs/{id}/retry` to `app/modules/executions/` | integration tests pass |
| P5-S07 | Export `openapi.json`, run `gen:api`, build frontend step timeline with attempts/errors, cancel/retry buttons, and credentials page | Vitest tests pass |
| P5-S08 | Labs (timeout ambiguity, worker kill recovery, 503 retry) + failure diagram (`docs/failure-recovery.md`) + progress log | recorded in `docs/lab-notes/phase-05.md` |

## Files
```text
alembic/versions/0004_tools_credentials.py
app/core/crypto.py
app/modules/integrations/{__init__,models,schemas,repository,service,router}.py
app/infrastructure/http_tool/{__init__,backoff,circuit_breaker,adapter}.py
app/workers/{runner,sweeper,scheduler}.py                       # modified / created
app/modules/executions/{schemas,repository,service,router}.py   # modified (cancel, retry)
tests/unit/{test_crypto,test_backoff,test_circuit_breaker}.py
tests/integration/{test_credentials,test_http_tool_adapter,test_sweeper_recovery,test_cancel_retry}.py
frontend/src/features/{credentials/CredentialsPage,runs/StepTimeline}.tsx
docs/failure-recovery.md   docs/lab-notes/phase-05.md
```

## Exact algorithms

### 1. Tool-Effect Ledger & HTTP Adapter (`app/infrastructure/http_tool/adapter.py`)
For step `step_id` of `run_id` with `idempotency_key = f"{run_id}:{step_id}"` and `provider = credential.provider if credential else url_host`:
1. **Pre-check ledger (before network call):**
   Query `tool_effects` for `(provider, idempotency_key)`.
   - If `state == 'COMMITTED'`: **do not make the HTTP call**. Return stored `response_summary` as the step output (prevents duplicate external side effects on worker retry/reclaim).
   - If `state == 'AMBIGUOUS'` (a previous `effect="write"` call timed out or dropped connection after bytes were sent): **do not automatically re-send** unless the step config has `provider_supports_idempotency: true` (default `true` when `Idempotency-Key` header is sent; if `false`, fail the run immediately with `error_code = 'TOOL_EFFECT_AMBIGUOUS'`).
   - Otherwise, upsert `tool_effects` with `state = 'INTENDED'`, `request_hash = sha256(canonical_json({method, url, headers, body}))`, and commit before opening the network socket.
2. **Allowlist & Egress check:**
   Verify URL scheme is `https` and hostname is in `(credential.allowed_hosts if credential else settings.egress_allowed_hosts)`. If not → fail non-retryably with `EGRESS_BLOCKED`. (Full IP-level DNS-rebinding defense is added in Phase 9).
3. **Circuit breaker check:**
   Per `provider` in-memory state (`CLOSED`, `OPEN`, `HALF_OPEN`): 5 consecutive 5xx/timeout errors open the circuit for 30 s; while `OPEN`, fail fast as retryable with `STEP_HTTP_ERROR`.
4. **HTTP Execution (`httpx.AsyncClient`, `follow_redirects=False`):**
   - Set timeout `httpx.Timeout(step.config.timeout_seconds, connect=5.0)`.
   - Set header `Idempotency-Key: {run_id}:{step_id}` and `X-Request-ID`.
   - If `credential_id` is configured, decrypt secret in memory just before sending and set `Authorization: Bearer <secret>` (never include in `step_attempts.input` or logs).
   - Stream response up to `65536` bytes (`64 KB`).
5. **Classify outcome & update ledger:**
   - `2xx`: update `tool_effects` to `state = 'COMMITTED'`, `external_ref = response_json.get("id")`, `response_summary = {"status": status_code, "body": body, "headers": safe_headers}`. Mark `step_attempts` `SUCCEEDED`.
   - `429` or `502/503/504`: update `tool_effects` to `state = 'FAILED'`, mark attempt `FAILED` with `retryable = True`, parse `Retry-After` (seconds or HTTP-date, capped at 120 s).
   - Connect timeout (`httpx.ConnectTimeout`, `httpx.ConnectError` — request never sent): `tool_effects.state = 'FAILED'`, `retryable = True`.
   - Read/Write timeout (`httpx.ReadTimeout`, `httpx.WriteTimeout`, `httpx.RemoteProtocolError` — server may have processed it): if `effect == 'write'`, set `tool_effects.state = 'AMBIGUOUS'`; mark attempt `FAILED` (`error_code = 'STEP_TIMEOUT'`, `retryable = step.config.get("provider_supports_idempotency", True)`).
   - Other `4xx`: `tool_effects.state = 'FAILED'`, `retryable = False`, `error_code = 'STEP_HTTP_ERROR'`.

### 2. Bounded Step Retries & Backoff (`app/infrastructure/http_tool/backoff.py`)
```python
def compute_backoff_seconds(
    attempt_no: int, retry_after: float | None = None, rng: Random | None = None
) -> float:
    cap = min(60.0, 2.0 * (2 ** (attempt_no - 1)))
    jittered = (rng or random).uniform(0.0, cap)
    if retry_after is not None:
        return min(120.0, max(jittered, retry_after))
    return jittered
```
When a step attempt fails:
- If `retryable` is `True` and `attempt_no < step.config.max_attempts`:
  Transition the run back to `QUEUED` with `next_attempt_at = now() + backoff`, `lease_owner = NULL`, `lease_expires_at = NULL`, keeping `current_step_id` on the failing step.
- Else (non-retryable or `attempt_no >= max_attempts`):
  Transition the run to `FAILED` (R7) with `error_code` (`STEP_RETRIES_EXHAUSTED` if attempts reached max, else the attempt's `error_code`).

### 3. Recovery Sweeper (`app/workers/sweeper.py`)
Runs every `sweeper_interval_seconds` (30 s):
1. Find runs that are either:
   - `state = 'RUNNING' AND lease_expires_at < now()` (dead worker lease), or
   - `state = 'QUEUED' AND next_attempt_at <= now()` and no unprocessed `outbox_events` row exists for the run.
2. For each (up to 100, `FOR UPDATE SKIP LOCKED`), insert an `outbox_events` row (`event_type = 'RunResumeRequested'`, `payload = {"run_id": str(run.id), "org_id": str(run.org_id)}`) so the outbox publisher dispatches a worker to claim/reclaim it via R2/R3.

### 4. Cancel and Manual Retry (`POST /v1/runs/{id}/cancel`, `POST /v1/runs/{id}/retry`)
- **Cancel:**
  - Try R9: `UPDATE workflow_runs SET state='CANCELLED', cancel_requested=true, finished_at=now(), updated_at=now() WHERE id=:id AND org_id=:org_id AND state IN ('QUEUED', 'WAITING_APPROVAL')`.
  - If rowcount is 0, try setting flag on `RUNNING`: `UPDATE workflow_runs SET cancel_requested=true, updated_at=now() WHERE id=:id AND org_id=:org_id AND state='RUNNING'`.
  - If both return 0 rows → raise `409 INVALID_STATE_TRANSITION` (run is already `SUCCEEDED`, `FAILED`, or `CANCELLED`).
- **Retry:**
  - Execute R11 (`WHERE id=:id AND org_id=:org_id AND state='FAILED'`) + insert `outbox_events(RunRequested)` in one transaction; return `202 Accepted`. If rowcount is 0 → `409 INVALID_STATE_TRANSITION`.
  - Completed steps (`SUCCEEDED` in `step_attempts`) and `COMMITTED` `tool_effects` are preserved and skipped when the worker runs.

## API contracts
| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `POST /v1/organizations/{org_id}/credentials` | `{"name": str, "provider": str, "secret": str(1–4096), "allowed_hosts": [str], "permission_scopes": [str]}` | `201` `CredentialOut` (no `secret` field) | 404; 403; 409 `CONFLICT`; 422 |
| `GET /v1/organizations/{org_id}/credentials` | `limit`, `cursor` | `200` page of `CredentialOut` | 404; 403 |
| `POST /v1/runs/{id}/cancel` | `{}` | `200` `RunDetail` | 404; 403; 409 `INVALID_STATE_TRANSITION` |
| `POST /v1/runs/{id}/retry` | `{}` | `202` `RunDetail` | 404; 403; 409 `INVALID_STATE_TRANSITION`; 429 `CONCURRENCY_LIMIT` |

`CredentialOut`: `{"id","org_id","name","provider","allowed_hosts","permission_scopes","key_id","created_at","rotated_at"}`.

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P5-T01 | test_crypto | Encrypt + decrypt round-trip works; wrong key or tampered ciphertext fails with ValueError; key rotation decrypts old `key_id` and encrypts with active `key_id` |
| P5-T02 | test_backoff | `compute_backoff_seconds` stays within `[0, cap]`; honours `Retry-After` when larger than random draw; caps at 120 s |
| P5-T03 | test_circuit_breaker | 5 consecutive failures open the breaker; calls while open fail immediately without hitting network; after cooldown transitions to half-open and closes on success |
| P5-T04 | test_credentials | Create credential → 201 without `secret` in JSON; DB `encrypted_secret` does not contain plaintext bytes; `GET` lists metadata only; viewer role gets 403 |
| P5-T05 | test_http_tool_adapter | `http_request` to allowlisted mock server succeeds, writes `tool_effects(COMMITTED)`, sends `Idempotency-Key: {run_id}:{step_id}`, and redacts `Authorization` header in `step_attempts` |
| P5-T06 | test_http_tool_adapter | Re-executing a step whose `tool_effects` is already `COMMITTED` returns stored summary and makes **0** additional HTTP requests |
| P5-T07 | test_http_tool_adapter | Upstream returns 503 twice then 200 on attempt 3 → 3 `step_attempts` rows (`FAILED`, `FAILED`, `SUCCEEDED`) and run ends `SUCCEEDED` |
| P5-T08 | test_http_tool_adapter | Upstream returns 503 on all `max_attempts=3` → run ends `FAILED` with `error_code="STEP_RETRIES_EXHAUSTED"` |
| P5-T09 | test_http_tool_adapter | ReadTimeout on `effect="write"` with `provider_supports_idempotency=False` sets `tool_effects.state="AMBIGUOUS"` and fails run with `TOOL_EFFECT_AMBIGUOUS` without sending a second POST |
| P5-T10 | test_http_tool_adapter | Request to host not in `allowed_hosts` fails immediately on attempt 1 with `EGRESS_BLOCKED` (`retryable=False`) |
| P5-T11 | test_sweeper_recovery | Simulate killed worker: run in `RUNNING` with `lease_expires_at < now()` and step 1 `COMMITTED` in `tool_effects`; sweeper enqueues `RunResumeRequested`; second worker reclaims (`attempt_epoch=2`), skips step 1's external HTTP call, executes step 2, and finishes `SUCCEEDED` |
| P5-T12 | test_cancel_retry | Cancel `QUEUED` run → immediately `CANCELLED`; cancel `RUNNING` run → sets `cancel_requested=true` and worker transitions to `CANCELLED` at next step boundary; cancel `SUCCEEDED` run → 409 `INVALID_STATE_TRANSITION` |
| P5-T13 | test_cancel_retry | `POST /v1/runs/{id}/retry` on `FAILED` run → 202 `QUEUED`, re-runs only from the failed step without repeating earlier `SUCCEEDED` steps |

## Frontend
- `CredentialsPage` (`/orgs/:orgId/credentials`): list credentials (`name`, `provider`, `allowed_hosts`, `permission_scopes`) + "Add credential" form (secret field is `type="password"`, cleared after submit, never displayed again).
- `StepTimeline` on `RunDetailPage`: groups `step_attempts` by `step_id`, showing each attempt badge (`Attempt #1 FAILED (503)`, `Attempt #2 SUCCEEDED`), duration, and redacted input/output/error.
- Cancel button (shown when `QUEUED`/`RUNNING`/`WAITING_APPROVAL`) and Retry button (shown when `FAILED`) on `RunDetailPage`.
- Frontend tests: `P5-F01` renders multiple attempts for a retried step; `P5-F02` Cancel and Retry buttons trigger respective endpoints and handle 409; `P5-F03` credential creation clears secret input and appends item.

## Labs (`docs/lab-notes/phase-05.md`)
1. **Unrecoverable tool ambiguity:** mock server records a side effect in a counter then sleeps past `timeout_seconds`. Compare outcome with `provider_supports_idempotency=False` (`AMBIGUOUS` halt, counter=1) vs naive retry without idempotency (counter=2) vs provider idempotency key deduplication (counter=1).
2. **Kill-worker mid-workflow:** start a 2-step workflow (`step1` HTTP write, `step2` HTTP write), terminate the worker after `step1` commits, let the sweeper recover it, and verify `step1` was called once and `step2` once.

## Verification commands
```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P5-T01…T13 and P5-F01…F03 pass.
- [ ] `docs/failure-recovery.md` and Labs 1–2 completed; Phase 5 PDF built.

## Agent brief
**Do:** always record `tool_effects(INTENDED)` before opening a socket and check `COMMITTED` before making any call. **Don't:** follow HTTP redirects (`follow_redirects=False` is mandatory) or log decrypted secrets. **Stop and report** if any race between `cancel` and step completion is not covered by the `attempt_epoch` and `state` SQL guards.
