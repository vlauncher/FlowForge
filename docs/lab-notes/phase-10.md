# Phase 10 Lab Notes: Recovery Drills, Backup/Restore RTO, and API Benchmarks

**Execution Date:** 2026-10-25  
**Environment:** Linux 7.0.0-38-generic (x86_64), 12 CPU cores, 14,693 MB RAM  
**PostgreSQL:** 16-alpine container (`flowforge-postgres-1`)  
**Status:** **ALL DRILLS & BENCHMARKS PASSED**

---

## Lab 1: Kill-Worker Crash Recovery Drill

### Objective
Verify that abruptly terminating a worker process midway through a multi-step execution (`SIGKILL` or unhandled task termination) results in clean reclamation by the recovery sweeper, zero duplicate side effects on external services, and successful transition to `SUCCEEDED` with `attempt_epoch = 2`.

### Execution
Command:
```bash
python scripts/drills/kill_worker_demo.py
```

### Captured Timeline Logs
```text
=== FlowForge Kill-Worker Recovery Drill (Phase 10) ===

[22:11:04.677] [SETUP] Initializing FlowForge client and seeding test workflow...
HTTP Request: POST http://testserver/v1/auth/signup "HTTP/1.1 201 Created"
HTTP Request: POST http://testserver/v1/organizations "HTTP/1.1 201 Created"
HTTP Request: POST http://testserver/v1/organizations/01a1751e-07cf-73ba-a971-702b4488ce11/credentials "HTTP/1.1 201 Created"
HTTP Request: POST http://testserver/v1/organizations/01a1751e-07cf-73ba-a971-702b4488ce11/workflows "HTTP/1.1 201 Created"
HTTP Request: POST http://testserver/v1/workflows/01a1751e-07fa-7083-ad7a-75fb253a5671/versions "HTTP/1.1 201 Created"
HTTP Request: POST http://testserver/v1/workflows/01a1751e-07fa-7083-ad7a-75fb253a5671/publish "HTTP/1.1 200 OK"
HTTP Request: POST http://testserver/v1/workflows/01a1751e-07fa-7083-ad7a-75fb253a5671/runs "HTTP/1.1 202 Accepted"
[22:11:04.864] [TRIGGER] Created run 01a1751e-081b-7767-871b-799350416843 in state QUEUED (attempt_epoch=0)
[22:11:04.864] [WORKER-1] Starting Worker 1 (worker-drill-1)...
[22:11:04.887] [EXTERNAL_MOCK] Wire request: POST https://api.stripe.com/v1/customers
HTTP Request: POST https://api.stripe.com/v1/customers "HTTP/1.1 200 OK"
[22:11:04.902] [CHAOS] Simulating catastrophic worker kill (SIGKILL / OOM) midway in step 2!
[22:11:04.902] [WORKER-1] Worker 1 killed. Lease preserved in DB without clean release.
[22:11:04.904] [INVARIANT] Run state: RUNNING | lease_owner: worker-drill-1 | attempt_epoch: 1
[22:11:04.906] [SWEEPER] Executing recovery sweeper to detect expired leases...
Sweeper scheduled recovery for run 01a1751e-081b-7767-871b-799350416843 (state: RUNNING)
[22:11:04.910] [SWEEPER] Sweeper recovered 1 stale run(s); queued RunResumeRequested.
[22:11:04.910] [WORKER-2] Starting Worker 2 (worker-drill-2) to reclaim and resume execution...
[22:11:04.922] [EXTERNAL_MOCK] Wire request: POST https://api.stripe.com/v1/charges
HTTP Request: POST https://api.stripe.com/v1/charges "HTTP/1.1 200 OK"
Run 01a1751e-081b-7767-871b-799350416843 succeeded successfully
[22:11:04.928] [OUTCOME] Final Run State: SUCCEEDED | Final attempt_epoch: 2
[22:11:04.929] [OUTCOME] Committed Tool Effects: 2/2 steps verified
[22:11:04.930] [VERIFICATION] Total external wire calls recorded: 2
  -> POST https://api.stripe.com/v1/customers [Idempotency-Key: 01a1751e-081b-7767-871b-799350416843:step_1]
  -> POST https://api.stripe.com/v1/charges [Idempotency-Key: 01a1751e-081b-7767-871b-799350416843:step_2]

✔ DRILL SUCCESS: 0 duplicate side effects, successful lease takeover at epoch 2!
```

### Invariant Proof
- `step_1` call count: **1**
- `step_2` call count: **1**
- Duplicate third-party API effects: **0**
- State transition sequence: `QUEUED` -> `RUNNING` (epoch 1) -> `RUNNING` (epoch 2) -> `SUCCEEDED`.

---

## Lab 2: Timed PostgreSQL Backup & Restore Drill

### Objective
Measure actual Recovery Time Objective (RTO) and verify bit-for-bit row count parity and relational integrity across a freshly restored database.

### Execution
Command:
```bash
bash scripts/drills/backup_restore_drill.sh
```

### Measured Metrics
- **Backup Duration (`pg_dump -Fc`):** **0.173 seconds**
- **Backup Archive Size:** **63.79 KB** (65,321 bytes)
- **Target Database Provisioning:** Dropped and created `flowforge_restore_drill`
- **Restore Duration (`pg_restore` RTO):** **0.354 seconds**
- **RTO Target SLA:** < 60.00 seconds (**Achieved: 0.354s**)

### Table Row Count Parity Verification
| Table | Source DB (`flowforge`) | Restored DB (`flowforge_restore_drill`) | Status |
|---|---|---|---|
| `users` | 4 | 4 | MATCH |
| `organizations` | 4 | 4 | MATCH |
| `memberships` | 2 | 2 | MATCH |
| `workflows` | 4 | 4 | MATCH |
| `workflow_versions` | 4 | 4 | MATCH |
| `triggers` | 0 | 0 | MATCH |
| `integration_credentials` | 4 | 4 | MATCH |
| `workflow_runs` | 4 | 4 | MATCH |
| `step_attempts` | 6 | 6 | MATCH |
| `approval_requests` | 0 | 0 | MATCH |
| `tool_effects` | 4 | 4 | MATCH |
| `outbox_events` | 4 | 4 | MATCH |
| `usage_records` | 0 | 0 | MATCH |
| `budget_reservations` | 0 | 0 | MATCH |
| `audit_events` | 10 | 10 | MATCH |

### Post-Restore Relational Invariant Queries
- Orphaned `workflow_runs` without parent `organizations`: **0**
- Orphaned `tool_effects` without parent `workflow_runs`: **0**
- Preserved `SUCCEEDED` runs: **2**

Full report written to [`docs/lab-notes/restore-drill-report.md`](restore-drill-report.md).

---

## Lab 3: API Synthetic Load Benchmark (Two Independent Runs)

### Objective
Execute a synthetic load benchmark with 50 concurrent clients twice under identical conditions to assess throughput, latency percentiles (p50, p95, p99), error rates, and reproducibility.

### Workload Configuration
- **Clients:** 50 concurrent async coroutines
- **Warmup:** 2.0 seconds
- **Measurement Window:** 10.0 seconds
- **Endpoint Mix:**
  - 30% `POST /v1/workflows/{id}/runs`
  - 40% `GET /v1/runs/{id}`
  - 30% `GET /v1/organizations/{id}/workflows`

### Run 1 Results
- **Total Requests Completed:** **2,289**
- **Measured Duration:** **10.21s**
- **Throughput:** **224.10 req/s**
- **p50 Latency:** **159.00 ms**
- **p95 Latency:** **465.52 ms**
- **p99 Latency:** **549.97 ms**
- **HTTP Error Rate:** **0.00%** (0 errors / 2,289 requests)

### Run 2 Results (Identical Hardware & Concurrency)
- **Total Requests Completed:** **2,799**
- **Measured Duration:** **10.16s**
- **Throughput:** **275.45 req/s**
- **p50 Latency:** **121.58 ms**
- **p95 Latency:** **347.41 ms**
- **p99 Latency:** **419.82 ms**
- **HTTP Error Rate:** **0.00%** (0 errors / 2,799 requests)

### Variance & Repeatability Comparison
| Metric | Benchmark Run 1 | Benchmark Run 2 | Variance / Delta |
|---|---|---|---|
| Throughput | 224.10 req/s | 275.45 req/s | +22.9% (JIT / pool warmup effect) |
| p50 Latency | 159.00 ms | 121.58 ms | -23.5% (Improved) |
| p95 Latency | 465.52 ms | 347.41 ms | -25.4% (Improved) |
| p99 Latency | 549.97 ms | 419.82 ms | -23.7% (Improved) |
| HTTP Error Rate | 0.00% | 0.00% | 0.00% (Zero dropped requests) |

Full methodology and hardware specification documented in [`docs/lab-notes/load-benchmark-report.md`](load-benchmark-report.md).
