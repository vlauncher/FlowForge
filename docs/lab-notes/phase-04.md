# Phase 4 Lab Notes: Durable Execution Core

## Lab 1: Crash Before Publish (Transactional Outbox Durability)

### Objective
Demonstrate that when a run is queued by the API while the outbox publisher / messaging broker is offline, no executions are lost. The queued run is queryable immediately by users via the API, and once the publisher recovers, the run transitions to `SUCCEEDED` automatically.

### Procedure
1. Stop the Celery worker and outbox publisher loop.
2. Submit a `POST /v1/workflows/{id}/runs` request to trigger a workflow.
3. Verify that `workflow_runs` contains a row in state `QUEUED` and `outbox_events` contains a row with `published_at IS NULL`.
4. Poll `GET /v1/runs/{id}` to verify the client observes the queued state (`200 OK`).
5. Start the outbox publisher loop and worker.
6. Verify the event is dispatched to RabbitMQ, claimed by the worker, and transitions to `SUCCEEDED`.

### Observations & Results
- API returned `202 Accepted` with `Location: /v1/runs/<run_id>`.
- Client was able to observe `QUEUED` state while the background broker was unreachable.
- Upon starting the publisher, `publish_batch` selected the unpublished row via `SELECT ... FOR UPDATE SKIP LOCKED` and published it with zero event loss.
- Run reached `SUCCEEDED` state with all steps executed in sequence.

---

## Lab 2: Duplicate Delivery Stress Test

### Objective
Verify that replaying identical `RunRequested` messages multiple times concurrently or sequentially produces exactly one attempt per workflow step and never double-executes steps.

### Procedure
1. Create and publish a 3-step workflow (`set_data -> condition -> set_data`).
2. Queue a workflow run `run_id`.
3. Deliver 5 concurrent execution invocations `execute_run(run_id)`.
4. Inspect `step_attempts` and `workflow_runs` state in PostgreSQL.

### Observations & Results
- Worker 1 successfully claimed the run, incrementing `attempt_epoch` from 0 to 1.
- Workers 2, 3, 4, and 5 saw 0 rows returned from the conditional `UPDATE ... WHERE state = 'QUEUED' ...` statement and exited cleanly with idempotent no-ops.
- `SELECT count(*) FROM step_attempts WHERE run_id = :id` returned exactly 3 rows (one per workflow step).
- `workflow_runs.state` settled in `SUCCEEDED` with outputs properly recorded.

---

## Lab 3: Stale Worker Fencing via `attempt_epoch`

### Objective
Demonstrate that a worker paused or stalled mid-step past its `lease_expires_at` is safely fenced when another worker reclaims the lease.

### Procedure
1. Worker A claims the run (`attempt_epoch = 1`).
2. Worker A's process is paused (simulated by advancing database clock past `lease_expires_at`).
3. Worker B reclaims the lease via the expired lease condition (`state = 'RUNNING' AND lease_expires_at < now()`), advancing `attempt_epoch` to 2.
4. Worker B executes the run to completion.
5. Worker A resumes and attempts to commit its step result guarded by `WHERE attempt_epoch = 1`.

### Observations & Results
- Worker B successfully claimed the run and advanced the fencing token (`attempt_epoch = 2`).
- Worker A's Transaction B update matched 0 rows because `attempt_epoch` in the database was 2.
- Worker A detected the fence, aborted its transaction cleanly, and did not overwrite Worker B's state.
- System integrity remained 100% sound with zero split-brain writes.
