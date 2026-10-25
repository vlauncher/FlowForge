# Runbook 08: Database Restore & Outbox Reconciliation

## 1. Symptom & Alert
- **Alert**: `FlowForgeDatabaseCatastrophicLoss` or scheduled disaster recovery drill.
- **PromQL**:
  ```promql
  flowforge_readiness_check{check="database"} == 0
  ```
- **Symptoms**: Primary database instance has suffered unrecoverable data corruption, hardware loss, or operator error requiring point-in-time or snapshot restoration.

## 2. Impact
- **Severity**: Critical (P1).
- **Blast Radius**: Platform is offline or in maintenance mode during restoration. RPO (Recovery Point Objective) equals the time between the last backup and the incident. RTO (Recovery Time Objective) target is < 15 minutes for 10 GB datasets.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# API 500 error rate during database outage
sum(rate(flowforge_http_requests_total{status=~"5.."}[5m]))
```

### PostgreSQL Status & Readiness Check
```bash
# Verify database connection status
docker compose exec flowforge-postgres pg_isready -U flowforge -d flowforge
```

## 4. Containment & Safe Recovery Steps

### Step 1: Place API and Workers in Maintenance Mode
Stop all write traffic to avoid partial state writes:
```bash
docker compose stop flowforge-api flowforge-worker flowforge-sweeper
```

### Step 2: Create Point-in-Time Dump of Current Database (if readable)
```bash
docker compose exec flowforge-postgres pg_dump -U flowforge -d flowforge -Fc -f /tmp/pre_restore_snapshot.dump
```

### Step 3: Provision Fresh Target Database or Drop Corrupt Schema
```bash
docker compose exec flowforge-postgres psql -U flowforge -c "DROP DATABASE IF EXISTS flowforge_restore_drill;"
docker compose exec flowforge-postgres psql -U flowforge -c "CREATE DATABASE flowforge_restore_drill OWNER flowforge;"
```

### Step 4: Restore Backup Archive with pg_restore
```bash
docker compose exec flowforge-postgres pg_restore -U flowforge -d flowforge_restore_drill -v /backups/latest_clean_backup.dump
```

### Step 5: Verify Post-Restore Invariants
Run the validation script or execute SQL verification queries:
```sql
-- 1. Table presence and row count sanity
SELECT 'users' AS tbl, count(*) FROM users
UNION ALL
SELECT 'organizations', count(*) FROM organizations
UNION ALL
SELECT 'workflows', count(*) FROM workflows
UNION ALL
SELECT 'workflow_runs', count(*) FROM workflow_runs
UNION ALL
SELECT 'tool_effects', count(*) FROM tool_effects;

-- 2. State invariant: No RUNNING runs should remain owned by dead worker leases
SELECT id, state, lease_owner, lease_expires_at
FROM workflow_runs
WHERE state = 'RUNNING'
  AND lease_expires_at > NOW();

-- 3. Reset stale leases to QUEUED for graceful recovery
UPDATE workflow_runs
SET state = 'QUEUED',
    lease_owner = NULL,
    next_attempt_at = NOW(),
    updated_at = NOW()
WHERE state = 'RUNNING';
```

### Step 6: Outbox Reconciliation
Reconcile unpublished outbox events against external message broker to prevent message loss or double-dispatch:
```sql
-- Mark already processed events as published to prevent redundant storm
UPDATE outbox_events
SET published_at = NOW()
WHERE published_at IS NULL
  AND created_at < NOW() - INTERVAL '1 hour';
```

### Step 7: Restart Application Services
```bash
docker compose start flowforge-api flowforge-worker flowforge-sweeper
curl -s http://localhost:8000/v1/health/ready | jq .
```

## 5. Escalation & Prevention
- **Escalation**: Escalate to CTO and Incident Commander if RPO exceeds 1 hour or backup checksums mismatch.
- **Prevention**:
  - Run automated daily backup verification drills (`scripts/drills/backup_restore_drill.sh`).
  - Retain 30 days of WAL archives for point-in-time recovery (PITR).
  - Store encrypted offsite backups in geographically distinct object storage.
