# Runbook 02: Stuck Running Task & Expired Worker Leases

## 1. Symptom & Alert
- **Alert**: `FlowForgeOldestQueuedRunAgeHigh` or `FlowForgeStaleLeaseDetected`
- **PromQL**:
  ```promql
  flowforge_oldest_queued_run_age_seconds > 300
  ```
  or
  ```promql
  sum(flowforge_active_runs{state="RUNNING"}) by (org_id) > 50
  ```
- **Symptoms**: Workflows remain in `RUNNING` status indefinitely with no new step attempts or log updates. Worker process may have crashed (OOMKilled, SIGKILL) without updating database state.

## 2. Impact
- **Severity**: Medium-High (P2).
- **Blast Radius**: Runs assigned to the dead or hung worker remain blocked until lease expiration and sweeper recovery. Execution throughput drops.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Oldest run age in queued state
flowforge_oldest_queued_run_age_seconds

# Total running executions vs queued executions
sum(flowforge_active_runs) by (state)
```

### PostgreSQL Diagnosis Queries
```sql
-- Find stuck RUNNING runs with expired leases (un-heartbeated > lease_seconds)
SELECT
    id AS run_id,
    org_id,
    lease_owner,
    attempt_epoch,
    lease_expires_at,
    heartbeat_at,
    NOW() - lease_expires_at AS expired_by
FROM workflow_runs
WHERE state = 'RUNNING'
  AND lease_expires_at < NOW()
ORDER BY lease_expires_at ASC
LIMIT 20;

-- Inspect worker host health and active leases
SELECT
    lease_owner,
    COUNT(*) AS active_leases,
    MIN(heartbeat_at) AS oldest_heartbeat
FROM workflow_runs
WHERE state = 'RUNNING'
GROUP BY lease_owner;
```

## 4. Containment & Safe Recovery Steps
1. **Trigger Immediate Sweeper Execution**:
   Run the recovery sweeper manually or trigger via worker container:
   ```bash
   python -c "
   import asyncio
   from app.infrastructure.db.session import get_session_factory
   from app.workers.sweeper import sweep_stale_and_delayed_runs
   asyncio.run(sweep_stale_and_delayed_runs(get_session_factory()))
   "
   ```
2. **Verify Outbox Re-enqueuing**:
   Confirm that the sweeper inserted `RunResumeRequested` events into `outbox_events`:
   ```sql
   SELECT aggregate_id, event_type, created_at, published_at
   FROM outbox_events
   WHERE event_type = 'RunResumeRequested'
     AND created_at >= NOW() - INTERVAL '5 minutes';
   ```
3. **Restart Faulty Worker Containers**:
   If a specific worker ID is hung (e.g. infinite loop in non-yielding sync code):
   ```bash
   docker restart flowforge-worker-1
   ```
4. **Verify Zero Duplicate Tool Execution**:
   Check `tool_effects` table to verify all committed steps preserved idempotency keys during resume:
   ```sql
   SELECT run_id, step_id, state, idempotency_key
   FROM tool_effects
   WHERE run_id = '<STUCK_RUN_ID>';
   ```

## 5. Escalation & Prevention
- **Escalation**: If sweeper fails to release runs or worker pool enters restart loops, escalate to Infrastructure On-Call.
- **Prevention**:
  - Keep `lease_seconds` (default 30s) and `heartbeat_seconds` (default 10s) tuned to workload duration.
  - Set timeouts on all step dispatchers (`timeout_seconds` in step configuration).
  - Enable Celery/Worker memory limit per child process (`--max-memory-per-child=500000`).
