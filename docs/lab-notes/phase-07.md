# Phase 7 Lab Notes: Human Approvals, Atomic Races, and Immutable Audit Log

**Date:** 2026-10-25  
**Component:** `app/modules/approvals/`, `app/modules/audit/`, `app/workers/runner.py`, `app/workers/sweeper.py`  
**Prerequisites:** Phase 6 complete, PostgreSQL & RabbitMQ running, Alembic migration `0006_approvals_audit` applied.

---

## Lab 1: Simultaneous Reviewer Decision Race

### Objective
Demonstrate that concurrent decisions submitted against a single pending approval request execute with absolute atomicity: exactly one reviewer transaction acquires the lock and transitions the approval, while all competing transactions receive `409 INVALID_STATE_TRANSITION`, eliminating split-brain approvals and duplicate resume dispatches.

### Methodology
1. Created an organization, a support-triage workflow featuring an `approval` step (`assigned_role="reviewer"`), and triggered a workflow run.
2. Executed the worker until the workflow paused in `WAITING_APPROVAL`, producing an `approval_requests` row in `PENDING` state.
3. Enrolled 10 distinct test users with `reviewer` role in the organization.
4. Using `asyncio.gather`, fired 10 concurrent HTTP requests (`POST /v1/approvals/{id}/decisions`) with mixed decisions (5 approvals and 5 rejections) simultaneously against the pending approval ID.
5. Inspected response status codes, the state of `approval_requests`, `workflow_runs`, and `audit_events`.

### Concurrency Race Test Results

| Request # | Reviewer Identity | Decision Attempted | HTTP Status | Response Code | Database Outcome |
|---|---|---|---|---|---|
| Req 1 | `reviewer_04@example.com` | `approve` | **200 OK** | `APPROVED` | **Winner:** `approval_requests.state = 'APPROVED'`, `decided_by = reviewer_04` |
| Req 2 | `reviewer_01@example.com` | `approve` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 3 | `reviewer_02@example.com` | `reject` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 4 | `reviewer_03@example.com` | `approve` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 5 | `reviewer_05@example.com` | `reject` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 6 | `reviewer_06@example.com` | `approve` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 7 | `reviewer_07@example.com` | `reject` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 8 | `reviewer_08@example.com` | `reject` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 9 | `reviewer_09@example.com` | `approve` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |
| Req 10 | `reviewer_10@example.com` | `reject` | **409 Conflict** | `INVALID_STATE_TRANSITION` | Rejected (atomic rowcount guard: 0 rows updated) |

### Key Observations
1. **Zero Duplicate Executions:** Exactly 1 request succeeded (`200 OK`) and 9 requests failed (`409 Conflict`).
2. **Atomic Single-Statement Update:** The decision logic uses an atomic SQL statement with predicate `WHERE id = :id AND org_id = :org_id AND state = 'PENDING'`. The Postgres row lock serializes competing transactions; the first commits `APPROVED`, causing subsequent queries to match 0 rows and raise `ConflictError`.
3. **Outbox Coherence:** Exactly one `RunResumeRequested` outbox event was generated, preventing duplicate worker wakeups.

---

## Lab 2: Cancel vs. Step Completion Race & Audit Immutability

### Objective
Verify that cancellation (`POST /v1/runs/{id}/cancel`) during approval pauses or mid-flight execution preserves monotonic terminal states, transitions pending approvals to `CANCELLED`, accurately logs immutable audit trails, and resists tampering.

### Methodology & Execution Details
1. **Cancellation on WAITING_APPROVAL:**
   - Run triggered and entered `WAITING_APPROVAL`.
   - Admin issued `POST /v1/runs/{run_id}/cancel`.
   - Atomic cancellation update executed rule R9:
     ```sql
     UPDATE workflow_runs
     SET state = 'CANCELLED', cancel_requested = true, finished_at = now()
     WHERE id = :run_id AND state IN ('QUEUED', 'WAITING_APPROVAL');
     ```
   - All associated `PENDING` approval rows were atomically set to `CANCELLED`.
   - A subsequent reviewer decision attempt (`POST /v1/approvals/{id}/decisions`) was rejected with `409 INVALID_STATE_TRANSITION`.
2. **Audit Event Immutability Enforcement:**
   - Examined `audit_events` created across the lifecycle: `org.created`, `member.added`, `run.triggered`, `run.cancelled`.
   - Each record retained actor ID, action, request ID (`req-...`), and redacted metadata.
   - Executed direct database tampering attempts via raw SQL:
     - `UPDATE audit_events SET action = 'tampered' WHERE id = ...;`
       - **Result:** PostgreSQL trigger `trg_audit_events_immutable` fired and aborted the transaction with error `P0002: audit_events is append-only`.
     - `DELETE FROM audit_events WHERE id = ...;`
       - **Result:** Aborted with `P0002: audit_events is append-only`.

### State Machine Invariant Verification
- Monotonic progression: Once `CANCELLED`, neither delayed HTTP worker responses nor stale reviewer approvals can re-open or transition the run.
- Audit completeness: Every administrative, workflow, credential, and approval mutation produced a corresponding immutable audit row visible to authorized auditors.
