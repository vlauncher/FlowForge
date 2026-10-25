# Runbook 05: Queue Saturation & Outbox Backlog Growth

## 1. Symptom & Alert
- **Alert**: `FlowForgeOutboxLagHigh` or `FlowForgeRabbitMQQueueHigh`
- **PromQL**:
  ```promql
  flowforge_outbox_lag_seconds > 60
  ```
  or
  ```promql
  rabbitmq_queue_messages_ready{queue="workflow_runs"} > 1000
  ```
- **Symptoms**: Workflows created by API are slow to begin execution. Database `outbox_events` table contains growing count of unpublished rows. Message queue shows sustained queue depth.

## 2. Impact
- **Severity**: High (P2).
- **Blast Radius**: Increased end-to-end execution latency for all tenants. If uncontained, database connection starvation or worker memory exhaustion may occur.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Outbox publisher lag in seconds
flowforge_outbox_lag_seconds

# Message publish rate vs consumption rate
sum(rate(flowforge_outbox_events_published_total[5m]))
sum(rate(flowforge_step_executions_total[5m]))
```

### PostgreSQL Diagnosis Queries
```sql
-- Count unpublished outbox events and age of oldest event
SELECT
    COUNT(*) AS unpublished_count,
    MIN(created_at) AS oldest_unpublished,
    NOW() - MIN(created_at) AS lag_interval
FROM outbox_events
WHERE published_at IS NULL;

-- Breakdown unpublished events by aggregate type and event type
SELECT
    aggregate_type,
    event_type,
    COUNT(*) AS count
FROM outbox_events
WHERE published_at IS NULL
GROUP BY aggregate_type, event_type
ORDER BY count DESC;

-- Check for stalled outbox dispatcher locks
SELECT pid, query_start, state, query
FROM pg_stat_activity
WHERE query LIKE '%outbox_events%'
  AND state != 'idle';
```

## 4. Containment & Safe Recovery Steps
1. **Scale Worker Concurrency**:
   Scale worker pool horizontally to increase consumption rate:
   ```bash
   docker compose up -d --scale flowforge-worker=4
   ```
2. **Verify RabbitMQ Cluster Connection**:
   Ensure outbox publisher process is alive and connected to RabbitMQ broker:
   ```bash
   curl -u guest:guest http://localhost:15672/api/queues/%2F/workflow_runs
   ```
3. **Manually Flush Stuck Outbox Batches**:
   If outbox dispatcher background task crashed, trigger batch publish sweep:
   ```bash
   python -c "
   import asyncio
   from app.infrastructure.db.session import get_session_factory
   from app.infrastructure.queue.dispatcher import dispatch_pending_outbox_events
   asyncio.run(dispatch_pending_outbox_events(get_session_factory()))
   "
   ```
4. **Purge Corrupt Messages to Dead-Letter Exchange (DLX)**:
   If poisoned messages cause crash loops, confirm DLX routing is routing bad events to `workflow_runs.dlq` without dropping valid tasks.

## 5. Escalation & Prevention
- **Escalation**: Escalate to Database Administrator if disk I/O latency on outbox table exceeds 50ms.
- **Prevention**:
  - Maintain partitioned `outbox_events` table or run periodic retention purges for published events (`DELETE FROM outbox_events WHERE published_at < NOW() - INTERVAL '7 days'`).
  - Implement producer rate limits to smooth ingestion spikes.
