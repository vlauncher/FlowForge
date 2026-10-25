# ADR-004: Duplicate Delivery Handling and Fencing Tokens

## Status
Accepted

## Context
In a distributed workflow execution system using RabbitMQ and Celery, network partitions, worker crashes, message re-deliveries (`redelivered=True`), and consumer timeouts inevitably cause the same execution message (`RunRequested`) to be delivered more than once to workers.

Without strict deduplication and fencing mechanisms, duplicate deliveries can lead to:
1. Double execution of external steps (e.g., duplicated payments or CRM records).
2. Race conditions where two workers concurrently advance different steps of the same workflow run.
3. Split-brain writes where a slow worker whose lease has expired commits state after a replacement worker has already claimed and progressed the run.

## Decision
We enforce a multi-layered defence based on:
1. **Idempotent Claim with Fencing Token (`attempt_epoch`):**
   Workers claim runs using atomic conditional SQL updates:
   ```sql
   UPDATE workflow_runs
   SET state = 'RUNNING',
       lease_owner = :worker_id,
       lease_expires_at = now() + :lease_interval,
       heartbeat_at = now(),
       attempt_epoch = attempt_epoch + 1,
       started_at = COALESCE(started_at, now()),
       updated_at = now()
   WHERE id = :run_id
     AND (
       (state = 'QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
       OR (state = 'RUNNING' AND lease_expires_at < now())
     )
   RETURNING attempt_epoch;
   ```
   If zero rows are returned, the run is already actively running or finished. The worker exits immediately with a clean no-op.

2. **Step-Level Deduplication via Ledger:**
   Before executing any step, the worker checks `step_attempts` for an existing `SUCCEEDED` record for `(run_id, current_step_id)`. If present, the step execution is skipped, its recorded output is loaded into `context`, and execution advances immediately.

3. **Two-Phase Guarded Step Transitions:**
   - **Transaction A (pre-step):** Inserts `step_attempts` with `status='RUNNING'` guarded by `WHERE attempt_epoch = :epoch`.
   - **Step execution:** Evaluated in memory or against external systems outside DB transactions.
   - **Transaction B (post-step):** Selects `workflow_runs WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch FOR UPDATE`. If zero rows match (because another worker reclaimed the run and incremented `attempt_epoch`), the stale worker is fenced and its commit is completely aborted.

4. **Background Heartbeat with Fencing Detection:**
   A background coroutine renews the lease every `heartbeat_seconds`. If an update yields 0 rows, it triggers a local `fenced_event` that halts the worker's step loop.

## Consequences
### Positive
- Exactly-once step attempt recording and idempotent terminal transitions even under arbitrary duplicate deliveries.
- Complete protection against zombie/stale workers writing stale state.
- Safe automated crash recovery when workers die mid-execution.

### Negative
- Requires maintaining heartbeat timers during step execution.
- Small lease overhead in database roundtrips during long-running workflows.
