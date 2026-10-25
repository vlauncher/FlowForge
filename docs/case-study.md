# FlowForge Engineering Case Study: Building a Resilient, Multi-Tenant AI Workflow Engine

**Author:** FlowForge Engineering Team  
**System:** FlowForge Durable Execution Engine  
**Classification:** Distributed Systems, Security Architecture, Fault Tolerance

---

## 1. Executive Summary
FlowForge is an open-source, durable workflow automation engine engineered to execute complex, multi-step AI agent workflows with strict fault tolerance, human-in-the-loop governance, multi-tenant isolation, and cryptographically verified external interactions. 

While conventional orchestrators (e.g., standard Celery, Temporal, Airflow) often treat workflow state and external API interactions as best-effort tasks—leading to duplicate credit charges, zombie process commits, and SSRF vulnerabilities—FlowForge establishes mathematical correctness invariants enforced directly at the storage, transport, and execution layers.

---

## 2. The Core Problem: Why Agent Orchestration Fails
Modern agentic workflows combining LLMs and third-party SaaS integrations present distinct failure modes:
1. **The Dual-Write Hazard:** Updating local application state in PostgreSQL while simultaneously publishing execution events to a message broker inevitably causes state desynchronization when either system fails mid-operation.
2. **Zombie Worker Overwrites:** When a worker process pauses (e.g., garbage collection, CPU starvation, temporary network partition) and loses its lease, a replacement worker reclaims the task. If the first worker awakens without fencing tokens, it can commit obsolete results over fresh state.
3. **The Non-Idempotent Side-Effect Problem:** When a node crashes after issuing an external API charge (e.g., Stripe, SendGrid) but before recording completion, a naive retry executes the charge twice.
4. **Adversarial Input & Prompt Injections:** Untrusted external inputs injected into downstream LLM prompts can hijack execution flow, compromise API tokens, or execute unauthorized lateral HTTP requests (SSRF).
5. **Runaway Multi-Tenant Cost Spikes:** A rogue agent workflow in a loop can exhaust organization budgets and starve platform resources.

---

## 3. Architecture & Durability Mechanics

### 3.1 Transactional Outbox Pattern
To eliminate the dual-write race between PostgreSQL and RabbitMQ, FlowForge never publishes directly to the broker during API requests or worker steps. Instead, state transitions and `OutboxEvent` records are written in the **exact same ACID transaction**:
```sql
BEGIN;
UPDATE workflow_runs SET state = 'QUEUED', ... WHERE id = :run_id;
INSERT INTO outbox_events (id, aggregate_type, aggregate_id, event_type, payload)
VALUES (:event_id, 'run', :run_id, 'RunCreated', :payload);
COMMIT;
```
A dedicated publisher process scans pending outbox rows using `SELECT ... FOR UPDATE SKIP LOCKED`, dispatches to RabbitMQ, and records `published_at = NOW()`.

### 3.2 Fencing Tokens & Attempt Epochs
To prevent zombie worker commits:
- Every run lease acquisition atomically increments `attempt_epoch = attempt_epoch + 1`.
- Step attempts and state transitions require matching the active attempt epoch.
- If a partitioned worker awakens and attempts to commit after another worker has reclaimed the lease, the database update fails cleanly (`WHERE attempt_epoch = :my_epoch`), preventing split-brain writes.

### 3.3 Three-State Tool-Effects Ledger
Every external side-effect is recorded in an append-only ledger before, during, and after dispatch:
- **`INTENDED`**: Written before dispatch with a deterministically hashed `idempotency_key` (e.g., `run_id:step_id`).
- **`COMMITTED`**: Updated upon receiving confirmed 2xx/3xx response from the upstream API.
- **`AMBIGUOUS`**: Marked if a network timeout occurs while waiting on the upstream socket.
Upon worker crash recovery, the resuming worker queries the ledger. If `COMMITTED`, the external HTTP call is skipped, preventing duplicate side effects.

---

## 4. Security & Isolation Invariants

### 4.1 SSRF Egress Validator with IP Pinning
External HTTP tools validate destination URLs against 15 blocked RFC ranges (e.g., `127.0.0.0/8`, `10.0.0.0/8`, `169.254.169.254/32`, `::1/128`, decimal/hex IP representations). To prevent DNS rebinding attacks (Time-of-Check to Time-of-Use), FlowForge resolves all IP addresses, verifies each address against the blocklist, pins the connection to the first validated IP address, and forces `sni_hostname` in TLS handshakes while disabling HTTP redirects.

### 4.2 Two-Phase Budget Reservations
To prevent budget race conditions under concurrent requests:
1. Before initiating an execution, the engine acquires a row-level lock on the organization (`SELECT budget_limit_micro_usd FROM organizations WHERE id = :org_id FOR UPDATE`).
2. It verifies `(committed_spend + reserved_spend + estimated_cost) <= budget_limit`.
3. If valid, it inserts a `budget_reservations` record in `RESERVED` state.
4. Upon step completion, the reservation is transitioned to `SETTLED` in the same transaction that inserts the immutable `usage_records`.

### 4.3 HMAC-SHA256 Signed Webhooks
Inbound webhooks enforce cryptographic signatures with a sliding ±300s replay window. Signatures are verified using constant-time comparison (`hmac.compare_digest`) to prevent timing side-channel attacks.

---

## 5. Performance Benchmarks & Recovery Evidence

### 5.1 Load Benchmark (50 Concurrent Clients)
- **Methodology:** 50 concurrent simulated client sessions executing a mixed workload (30% workflow run triggers, 40% run status polling, 30% workflow queries) over a 30-second sustained window following a 5-second warmup period.
- **Hardware Profile:** Linux x86_64, 8 cores, 16 GB RAM, PostgreSQL 16 container with NVMe SSD backing.
- **Measured Metrics:**
  - Throughput: **218.4 requests / second**
  - p50 Latency: **8.2 ms**
  - p95 Latency: **34.1 ms**
  - p99 Latency: **68.7 ms**
  - HTTP Error Rate: **0.00%** (0 failed requests out of 6,552 requests).

### 5.2 Kill-Worker Crash Recovery Drill
- Worker 1 was killed mid-run via `SIGKILL` immediately after step 1 committed its external side-effect to Stripe.
- Sweeper identified the expired lease at $t + 5\text{s}$, enqueued a recovery event, and Worker 2 reclaimed execution at `attempt_epoch = 2`.
- Verification verified:
  - Total external calls to Step 1: **Exactly 1**.
  - Total external calls to Step 2: **Exactly 1**.
  - Final Run State: **`SUCCEEDED`**.
  - Duplicate side-effects: **0**.

### 5.3 Database Disaster Recovery (RTO / RPO Drill)
- Point-in-time `pg_dump -Fc` performed on active multi-tenant database.
- Restored with `pg_restore` into clean target database.
- RTO (Recovery Time Objective): **2.18 seconds** for complete schema, indices, triggers, and state table restoration.
- Row count and foreign key invariant check: **100% match, 0 corrupted rows**.

---

## 6. Release Gates Verification Matrix (G1–G6)

Every release gate is verified through concrete automated tests and specification contracts in the repository:

| Gate | Description | Verified Repository Artifacts & Evidence |
|---|---|---|
| **G1: Specification** | PRD + tests define allowed and forbidden behavior | [`docs/00-problem.md`](00-problem.md), [`spec/00-global.md`](../spec/00-global.md), `openapi.json`, `P1-T15` |
| **G2: Data Correctness** | Tests fail on invalid transitions and races | `alembic/versions/0001..0007`, `P2-T19..T23`, `P3-T11`, `P4-T10..T11`, `P7-T05` |
| **G3: Security** | Cross-tenant, unauthenticated, and replay attacks denied | [`docs/threat-model.md`](threat-model.md), `P2-T10`, `P6-T09`, `P7-T06`, `P9-T01..T08` |
| **G4: Recovery** | Kill worker/provider gives correct outcome or declared limit | [`docs/failure-recovery.md`](failure-recovery.md), `P5-T06..T11`, `P10-T01`, [`docs/lab-notes/restore-drill-report.md`](lab-notes/restore-drill-report.md) |
| **G5: Operations** | Traces, dashboards, restore, and rollback documented | `infra/observability/`, `docs/runbooks/01..08`, [`docs/postmortems/PM-001-worker-lease-stall.md`](postmortems/PM-001-worker-lease-stall.md), `P8-T02..T04` |
| **G6: Communication** | ADRs show alternatives, assumptions, costs, evidence | `docs/adr/ADR-001..005`, [`docs/case-study.md`](case-study.md), [`docs/architecture/10x-scaling-proposal.md`](architecture/10x-scaling-proposal.md) |

---

## 7. Honest Technical Trade-offs & Limitations
In the spirit of honest distributed systems engineering:
1. **Single-Region Database Bottleneck:** Current architecture utilizes a single PostgreSQL primary. Cross-region multi-master is not supported; failover requires DNS cutover to a warm replica.
2. **Synchronous Tool Call Suspension:** While external tool execution enforces socket deadlines (30s), a worker thread remains dedicated to the in-flight HTTP request rather than parking execution in a coroutine event loop.
3. **Approval Expiration Semantics:** Expired human approval requests transition the entire workflow run to `FAILED`. Resuming an expired run requires triggering a new run; in-place resumption of expired approvals is intentionally prohibited by the state machine design.
