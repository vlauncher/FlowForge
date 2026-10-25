# Phase 4 Spec: Durable Execution Core

Learning material: `flowforge.md` → Phase 4. Contracts: `spec/00-global.md` (§3 tables `workflow_runs`, `step_attempts`, `outbox_events`; §4 state machines R1–R3, R6, R7; §6 worker parameters; §7 errors; §8 API surface; §11 RabbitMQ topology). **Prerequisite:** Phase 3 done-when is green.

## Scope
Migration `0003_runs_outbox`, `POST /v1/workflows/{id}/runs` (`202 Accepted`) with `Idempotency-Key` and request fingerprint, atomic `Run(QUEUED)` + `outbox_events` write, RabbitMQ topology declaration, outbox publisher loop, Celery worker claiming runs with lease + fencing token (`attempt_epoch`) + background heartbeat, deterministic execution of `set_data` and `condition` steps (external HTTP is Phase 5, LLM is Phase 6, approvals are Phase 7), step attempt persistence, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/steps`, `GET /v1/organizations/{org_id}/runs`, and frontend run trigger + live-polling run detail page.

## Config additions (`Settings`)
`rabbitmq_url="amqp://flowforge:flowforge@localhost:5672//"`, `celery_task_queue="runs.execute"`, `lease_seconds=60`, `heartbeat_seconds=15`, `sweeper_interval_seconds=30`.

## Steps
| ID | Step | Done when |
|---|---|---|
| P4-S01 | Add `rabbitmq` to `compose.yaml` (management image, healthcheck `rabbitmq-diagnostics -q ping`, ports `127.0.0.1:5672:5672` and `127.0.0.1:15672:15672`); add `worker` and `scheduler` services | `docker compose up -d postgres rabbitmq` healthy |
| P4-S02 | Revision `0003_runs_outbox` (`workflow_runs`, `step_attempts`, `outbox_events` with all constraints and partial indexes from spec §3) | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds |
| P4-S03 | `app/domain/run_state_machine.py` & `app/domain/template_engine.py` (pure template resolution + condition evaluation) | unit tests pass |
| P4-S04 | `app/modules/executions/{models,schemas,repository,service,router}.py`: trigger run (`202`), idempotency check, concurrency cap check, get run, list runs, list step attempts | integration tests pass |
| P4-S05 | `app/infrastructure/messaging/{topology,outbox_publisher}.py` and `app/workers/{celery_app,tasks,runner,scheduler}.py` | worker + outbox tests pass |
| P4-S06 | Register `broker` readiness check; export `openapi.json`; `gen:api` | `/ready` checks `db` and `broker` |
| P4-S07 | Frontend run trigger dialog, runs list, and polling run detail page (`refetchInterval: 2000` while non-terminal) | Vitest tests pass |
| P4-S08 | Labs (crash before publish, crash before ack, duplicate delivery) + ADR-004 + progress log | recorded in `docs/lab-notes/phase-04.md` and `docs/adr/ADR-004-duplicate-delivery.md` |

## Files
```text
alembic/versions/0003_runs_outbox.py
app/domain/{run_state_machine,template_engine}.py
app/modules/executions/{__init__,models,schemas,repository,service,router}.py
app/infrastructure/messaging/{__init__,topology,outbox_publisher}.py
app/workers/{__init__,celery_app,tasks,runner,scheduler}.py
tests/unit/{test_run_state_machine,test_template_engine}.py
tests/integration/{test_runs_api,test_outbox_publisher,test_worker_execution,test_duplicate_delivery}.py
frontend/src/features/runs/{RunsListPage,RunDetailPage,TriggerRunModal}.tsx
docs/lab-notes/phase-04.md   docs/adr/ADR-004-duplicate-delivery.md
```

## Exact algorithms

### 1. Trigger Run (`POST /v1/workflows/{id}/runs`)
1. Verify caller has `run.trigger` in the workflow's org (join workflow + membership; missing → `404`, wrong role → `403`).
2. Resolve version: if body specifies `workflow_version: int`, load that published version; else load `workflow.current_version_id`. If workflow is archived or version is not `published` → `409 VERSION_NOT_PUBLISHED`.
3. Validate `inputs` against `definition_json.inputs_schema` (`jsonschema.Draft202012Validator`). On failure → `422 VALIDATION_ERROR`.
4. Compute `request_fingerprint = sha256(canonical_json({"version_id": str(version.id), "inputs": inputs}))`.
5. If `Idempotency-Key` header is present:
   - Query `workflow_runs` for `(org_id, idempotency_key)`.
   - If found and `request_fingerprint` matches → return `202` with the existing run and header `Idempotency-Replayed: true`.
   - If found and `request_fingerprint` differs → raise `409 IDEMPOTENCY_KEY_REUSED`.
6. Lock the `organizations` row `SELECT id, max_concurrent_runs FROM organizations WHERE id = :org_id FOR UPDATE` (serializes concurrent run creation per org) and count `SELECT count(*) FROM workflow_runs WHERE org_id = :org_id AND state IN ('QUEUED', 'RUNNING')`. If `count >= max_concurrent_runs` → raise `429 CONCURRENCY_LIMIT`.
7. In the same transaction:
   - `INSERT INTO workflow_runs` (`state='QUEUED'`, `current_step_id=definition.start`, `next_attempt_at=now()`, `attempt_epoch=0`, ...). On unique violation on `(org_id, idempotency_key)`, roll back and repeat step 5.
   - `INSERT INTO outbox_events` (`aggregate_type='run'`, `aggregate_id=run.id`, `event_type='RunRequested'`, `payload={"run_id": str(run.id), "org_id": str(org_id), "request_id": get_request_id()}`).
   - Commit. Return `202 Accepted`.

### 2. Outbox Publisher (`app/infrastructure/messaging/outbox_publisher.py`)
```python
async def publish_batch(session_factory, broker_publish, batch_size: int = 100) -> int:
    # 1. Select batch with row lock
    # SELECT * FROM outbox_events WHERE published_at IS NULL AND next_publish_at <= now()
    # ORDER BY created_at ASC, id ASC LIMIT :batch_size FOR UPDATE SKIP LOCKED
    # 2. For each event, publish Celery task signature `runs.execute_run(run_id)` with task_id = str(event.id)
    # 3. On publish success: UPDATE outbox_events SET published_at = now() WHERE id = :id
    # 4. On publish exception: UPDATE outbox_events SET publish_attempts = publish_attempts + 1,
    #    next_publish_at = now() + make_interval(secs => least(60, 2 ^ publish_attempts)) WHERE id = :id
```

### 3. Worker Claim, Heartbeat, and Step Loop (`app/workers/runner.py`)
1. **Claim:** Execute single statement:
   ```sql
   UPDATE workflow_runs
   SET state = 'RUNNING',
       lease_owner = :worker_id,
       lease_expires_at = now() + make_interval(secs => :lease_seconds),
       heartbeat_at = now(),
       attempt_epoch = attempt_epoch + 1,
       started_at = COALESCE(started_at, now()),
       updated_at = now()
   WHERE id = :run_id
     AND (
       (state = 'QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
       OR (state = 'RUNNING' AND lease_expires_at < now())
     )
   RETURNING id, org_id, version_id, current_step_id, inputs, context, attempt_epoch, cancel_requested;
   ```
   If no row is returned (already `RUNNING` with a valid lease, or already terminal / `WAITING_APPROVAL`), **return cleanly** (idempotent no-op).
2. **Heartbeat task:** Start an `asyncio.Task` every `heartbeat_seconds`:
   ```sql
   UPDATE workflow_runs
   SET lease_expires_at = now() + make_interval(secs => :lease_seconds),
       heartbeat_at = now(), updated_at = now()
   WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch;
   ```
   If `rowcount == 0`, set a local `fenced_event` so the step loop aborts immediately.
3. **Step execution loop** (bounded by `MAX_STEPS_PER_RUN = 100`):
   - Re-check `cancel_requested`: if true, transition to `CANCELLED` (R10) and stop.
   - Check if `current_step_id` already has a `SUCCEEDED` row in `step_attempts` for this `run_id`. If so, ensure its `output` is in `context[step_id]`, advance `current_step_id` to the next step, and continue.
   - Determine `attempt_no = COALESCE(MAX(attempt_no), 0) + 1` for `(run_id, current_step_id)`.
   - **Transaction A (before external/step work):** verify `workflow_runs` still has `attempt_epoch = :epoch`; `INSERT INTO step_attempts` (`status='RUNNING'`, `input=redact(resolved_input)`, `epoch=:epoch`, `started_at=now()`). Commit.
   - **Execute step outside DB transaction:** in Phase 4, execute `set_data` or `condition` (pure in-memory evaluation via `template_engine.py`).
   - **Transaction B (record step result):** verify `workflow_runs` still has `state='RUNNING' AND attempt_epoch = :epoch` (`SELECT id FROM workflow_runs WHERE id=:run_id AND state='RUNNING' AND attempt_epoch=:epoch FOR UPDATE`). If 0 rows → abort (fenced).
     - Update `step_attempts` (`status='SUCCEEDED'`, `output=redact(output)`, `ended_at=now()`, `duration_ms=...`).
     - Update `context[step_id] = output` and `current_step_id = next_step_id` on `workflow_runs`.
     - If `next_step_id is None`, set `state='SUCCEEDED'`, `outputs=output`, `finished_at=now()`, `lease_owner=NULL`, `lease_expires_at=NULL` (R6).
     - Commit.

## API contracts
| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `POST /v1/workflows/{id}/runs` | Header `Idempotency-Key` (optional); body `{"inputs": <object>, "workflow_version"?: int}` | `202` `RunResponse` + `Location: /v1/runs/{run_id}` | 404; 403; 409 `VERSION_NOT_PUBLISHED`, `IDEMPOTENCY_KEY_REUSED`; 422 `VALIDATION_ERROR`; 429 `CONCURRENCY_LIMIT` |
| `GET /v1/organizations/{org_id}/runs` | `limit`, `cursor`, `state` (optional), `workflow_id` (optional) | `200` page of `RunSummary` | 404; 400 |
| `GET /v1/runs/{id}` | — | `200` `RunDetail` | 404 |
| `GET /v1/runs/{id}/steps` | — | `200` `{"items": [StepAttempt]}` (ordered by `started_at ASC, attempt_no ASC`) | 404 |

`RunResponse`: `{"run_id": uuid, "state": "QUEUED", "workflow_id": uuid, "workflow_version": int, "version_id": uuid, "status_url": "/v1/runs/<id>", "created_at": iso}`.
`RunDetail`: adds `inputs`, `outputs`, `current_step_id`, `error_code`, `error_detail`, `started_at`, `finished_at`.

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P4-T01 | test_run_state_machine | All valid transitions R1–R11 accepted; illegal transitions (`SUCCEEDED -> RUNNING`, `CANCELLED -> RUNNING`) rejected |
| P4-T02 | test_template_engine | Resolves single placeholder preserving type (int/bool/dict); interpolates mixed string; evaluates all `condition` ops (`eq`, `neq`, `gt`, `in`, `exists`) |
| P4-T03 | test_runs_api | `POST /v1/workflows/{id}/runs` returns `202` and persists both `workflow_runs(QUEUED)` and `outbox_events(unpublished)` in the same transaction |
| P4-T04 | test_runs_api | Same `Idempotency-Key` + same body twice → single `workflow_runs` row, second response has `Idempotency-Replayed: true`; same key + different body → `409 IDEMPOTENCY_KEY_REUSED` |
| P4-T05 | test_runs_api | Triggering on a workflow with no published version → `409 VERSION_NOT_PUBLISHED`; invalid `inputs` against `inputs_schema` → `422 VALIDATION_ERROR` |
| P4-T06 | test_runs_api | When org has `max_concurrent_runs` active (`QUEUED`/`RUNNING`) runs, an extra run request returns `429 CONCURRENCY_LIMIT` |
| P4-T07 | test_outbox_publisher | `publish_batch` publishes unpublished events, sets `published_at`, and two concurrent `publish_batch` calls (`SKIP LOCKED`) never publish the same row in the same batch |
| P4-T08 | test_outbox_publisher | Broker failure increments `publish_attempts` and pushes `next_publish_at` into the future |
| P4-T09 | test_worker_execution | End-to-end 3-step workflow (`set_data -> condition -> set_data`) transitions `QUEUED -> RUNNING -> SUCCEEDED`, populates `outputs`, and records 3 `step_attempts` |
| P4-T10 | test_duplicate_delivery | Calling `execute_run(run_id)` twice concurrently or sequentially produces exactly 1 attempt per step and 1 terminal `SUCCEEDED` transition |
| P4-T11 | test_duplicate_delivery | Fencing test: Worker A claims run (`epoch=1`), lease expires, Worker B reclaims run (`epoch=2`); Worker A attempting to commit a step result with `epoch=1` is rejected and does not overwrite Worker B |
| P4-T12 | test_runs_api | Cross-tenant `GET /v1/runs/{id}` and `GET /v1/runs/{id}/steps` return `404` |

## Frontend
- `TriggerRunModal` on `WorkflowDetailPage`: generates a fresh UUIDv7 `Idempotency-Key` when the modal opens (kept across retries of the same submission so network retries are idempotent), takes JSON inputs, submits `POST /v1/workflows/{id}/runs`, and navigates to `/orgs/:orgId/runs/:runId`.
- `RunsListPage` (`/orgs/:orgId/runs`): state filter (`ALL`, `QUEUED`, `RUNNING`, `WAITING_APPROVAL`, `SUCCEEDED`, `FAILED`, `CANCELLED`), cursor pagination.
- `RunDetailPage` (`/orgs/:orgId/runs/:runId`): polls `GET /v1/runs/{id}` and `GET /v1/runs/{id}/steps` every 2 s while `state` is `QUEUED`, `RUNNING`, or `WAITING_APPROVAL`; stops polling once terminal. Displays state badge, inputs, outputs, and step timeline.
- Frontend tests: `P4-F01` reuses the same `Idempotency-Key` on retry; `P4-F02` polls while `RUNNING` and stops when `SUCCEEDED`; `P4-F03` renders step attempts in order.

## Labs (`docs/lab-notes/phase-04.md`)
1. **Crash before publish:** insert `Run(QUEUED)` + `outbox_events` row with the publisher stopped; verify the run is visible via `GET /v1/runs/{id}`; start the publisher and verify the run completes.
2. **Duplicate delivery:** deliver the same `RunRequested` message 5 times to the worker; verify `SELECT count(*) FROM step_attempts WHERE run_id = :id` equals the number of workflow steps.
3. **Stale worker fencing:** pause Worker A mid-step beyond `lease_seconds`, let Worker B reclaim, then resume Worker A and show its write is rejected by the `attempt_epoch` guard.

## Verification commands
```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P4-T01…T12 and P4-F01…F03 pass.
- [ ] Labs 1–3 recorded; ADR-004 written; Phase 4 PDF built.

## Agent brief
**Do:** keep DB transactions short (never hold a transaction open during step execution). **Don't:** implement external HTTP calls, LLM calls, or approvals in this phase. **Stop and report** if Celery + asyncio loop integration requires an extra library not in `spec/00-global.md` §12 (use `asyncio.run` inside a sync Celery task or a dedicated worker loop per module).
