# Phase 7 Spec: Human Approvals, RBAC, and Audit Trail

Learning material: `flowforge.md` → Phase 7. Contracts: `spec/00-global.md` (§2 role matrix and `assigned_role` ordering; §3 tables `approval_requests`, `audit_events`; §4 state machines R4, R5, R8, R9; §5 `approval` step; §7 errors; §8 API surface). **Prerequisite:** Phase 6 done-when is green.

## Scope
Migration `0006_approvals_audit` (`approval_requests`, `audit_events` + append-only DB trigger), worker execution of `approval` step (pauses run into `WAITING_APPROVAL`, creates pending approval request), race-safe approval decision endpoint (`POST /v1/approvals/{id}/decisions`) with decision-time role hierarchy verification (`reviewer < admin < owner`), sweeper expiration of stale approvals, runtime enforcement of approval before irreversible `http_request` execution, append-only `audit_events` recording and query API, and frontend Approval Inbox + Audit Log pages.

## Steps
| ID | Step | Done when |
|---|---|---|
| P7-S01 | Revision `0006_approvals_audit` (`approval_requests`, `audit_events`, and `forbid_audit_mutation` trigger) | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds |
| P7-S02 | `app/modules/audit/{models,schemas,repository,service,router}.py`: append-only `record_audit_event(...)` helper (redacts metadata, attaches `request_id`) and `GET /v1/organizations/{org_id}/audit-events` | unit + integration tests pass |
| P7-S03 | Wire `record_audit_event` into auth (`user.signup`, `user.login`), org/member changes (`member.added`, `member.role_changed`), workflow publish (`workflow.published`), credentials (`credential.created`), and run lifecycle (`run.triggered`, `run.cancelled`, `run.retried`) | audit integration tests pass |
| P7-S04 | `app/modules/approvals/{models,schemas,repository,service,router}.py`: list, get, and race-safe `decide_approval` (`approve` / `reject`) | integration + concurrency tests pass |
| P7-S05 | Extend `app/workers/runner.py` for `approval` step (R4) and runtime irreversible-tool gate; extend `app/workers/sweeper.py` for expired approvals (R8) and `cancel` service for pending approvals (R9) | worker + sweeper approval tests pass |
| P7-S06 | Export `openapi.json`, run `gen:api`, build frontend `ApprovalsPage`, `ApprovalBanner` on `RunDetailPage`, and `AuditEventsPage` | Vitest tests pass |
| P7-S07 | Labs (concurrent approval race, cancel-vs-complete race, revoked role at decision time) + progress log | recorded in `docs/lab-notes/phase-07.md` |

## Files
```text
alembic/versions/0006_approvals_audit.py
app/modules/audit/{__init__,models,schemas,repository,service,router}.py
app/modules/approvals/{__init__,models,schemas,repository,service,router}.py
app/workers/{runner,sweeper}.py                                 # modified
app/modules/{identity,organizations,workflows,integrations,executions}/service.py  # audit hooks
tests/unit/test_approval_roles.py
tests/integration/{test_approvals,test_approval_races,test_audit_events}.py
frontend/src/features/{approvals/ApprovalsPage,audit/AuditEventsPage,runs/ApprovalBanner}.tsx
docs/lab-notes/phase-07.md
```

## Database & algorithm contracts

### 1. Audit Append-Only Trigger (`0006_approvals_audit.py`)
```sql
CREATE FUNCTION forbid_audit_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'P0002';
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION forbid_audit_mutation();
```

### 2. Worker `approval` Step Execution (`app/workers/runner.py`)
When `current_step_id` is an `approval` step:
1. Check if an `approval_requests` row for `(run_id, step_id)` already exists with `state = 'APPROVED'` and `version_id = run.version_id`:
   - If yes: record `step_attempts(SUCCEEDED)` with `output = {"decision": "approved", "decided_by": str(req.decided_by), "decided_at": req.decided_at.isoformat()}`, advance `current_step_id = step.next`, and continue the step loop.
2. Otherwise, in one transaction (fenced by `attempt_epoch`):
   - Render `summary` template via `template_engine` and pass through `redact()`.
   - `INSERT INTO approval_requests` (`org_id`, `run_id`, `step_id`, `version_id = run.version_id`, `assigned_role = step.config.assigned_role`, `state = 'PENDING'`, `summary = redacted_summary`, `expires_at = now() + make_interval(secs => step.config.expires_in_seconds)`).
   - Transition run via R4:
     ```sql
     UPDATE workflow_runs
     SET state = 'WAITING_APPROVAL', lease_owner = NULL, lease_expires_at = NULL,
         current_step_id = :step_id, updated_at = now()
     WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch;
     ```
   - Commit and exit worker cleanly.

### 3. Race-Safe Approval Decision (`POST /v1/approvals/{id}/decisions`)
1. Load `approval_requests` joined with caller's `memberships` on `org_id`. If no row → `404 NOT_FOUND`.
2. **Decision-time RBAC check:**
   - Caller's current role in `memberships` must have `approval.decide` (`reviewer`, `admin`, or `owner`) **and** must satisfy `ROLE_RANK[caller_role] >= ROLE_RANK[approval.assigned_role]` where `ROLE_RANK = {"viewer": 0, "operator": 1, "reviewer": 2, "admin": 3, "owner": 4}`. If not → `403 FORBIDDEN`.
3. **Atomic conditional UPDATE on `approval_requests`:**
   ```sql
   UPDATE approval_requests
   SET state = :new_state,          -- 'APPROVED' or 'REJECTED'
       decided_by = :user_id,
       decided_at = now(),
       decision_comment = :comment
   WHERE id = :approval_id
     AND org_id = :org_id
     AND state = 'PENDING'
     AND expires_at > now()
   RETURNING run_id, step_id, version_id;
   ```
   - If `rowcount == 0`: re-read the row. If `expires_at <= now()`, transition it to `EXPIRED` (if still `PENDING`), commit, and raise `409 INVALID_STATE_TRANSITION` (`detail="Approval request has expired"`). Otherwise (`state != 'PENDING'`), raise `409 INVALID_STATE_TRANSITION` (`detail="Approval request already decided"`).
4. **In the same transaction**, update `workflow_runs`:
   - If `APPROVED` (R5):
     ```sql
     UPDATE workflow_runs
     SET state = 'QUEUED', next_attempt_at = now(), updated_at = now()
     WHERE id = :run_id AND version_id = :version_id AND state = 'WAITING_APPROVAL';
     ```
     If `rowcount != 1` → raise `409 INVALID_STATE_TRANSITION` (rolls back the approval update too).
     Insert `outbox_events` (`event_type = 'RunResumeRequested'`, `payload = {"run_id": str(run_id), "org_id": str(org_id)}`).
   - If `REJECTED` (R8):
     ```sql
     UPDATE workflow_runs
     SET state = 'FAILED', error_code = 'APPROVAL_REJECTED',
         error_detail = 'Rejected by reviewer', finished_at = now(), updated_at = now()
     WHERE id = :run_id AND state = 'WAITING_APPROVAL';
     ```
   - Insert `audit_events` (`action = "approval.approved"` or `"approval.rejected"`, `target_type = "approval_request"`, `target_id = approval_id`, `redacted_metadata = {"run_id": str(run_id), "step_id": step_id, "comment": comment}`).
   - Commit.

### 4. Approval Expiry in Sweeper (`app/workers/sweeper.py`)
Every sweep cycle:
1. Select up to 100 rows `SELECT id, org_id, run_id FROM approval_requests WHERE state = 'PENDING' AND expires_at <= now() FOR UPDATE SKIP LOCKED`.
2. For each: update `approval_requests SET state = 'EXPIRED'`, update `workflow_runs SET state = 'FAILED', error_code = 'APPROVAL_EXPIRED', finished_at = now() WHERE id = :run_id AND state = 'WAITING_APPROVAL'`, and write an `audit_events` row (`actor_type = 'system'`, `action = 'approval.expired'`).

### 5. Runtime Irreversible-Tool Gate (`app/workers/runner.py`)
Before executing an `http_request` step where `effect == "write"` and the credential has `"irreversible"` in `permission_scopes`:
- Query `approval_requests` for this `run_id` and `version_id` with `state = 'APPROVED'` whose `step_id` is in $\text{Dom}(\text{current\_step\_id})$. If none exists, fail the run immediately (`error_code = 'FORBIDDEN_TOOL_PERMISSION'`, `retryable = False`).

## API contracts
| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /v1/organizations/{org_id}/approvals` | `limit`, `cursor`, `state` (optional: `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CANCELLED`) | `200` page of `ApprovalOut` | 404; 400 |
| `GET /v1/approvals/{id}` | — | `200` `ApprovalOut` | 404 |
| `POST /v1/approvals/{id}/decisions` | `{"decision": "approve"\|"reject", "comment"?: str(≤1000)}` | `200` `ApprovalOut` | 404; 403 (`FORBIDDEN`); 409 `INVALID_STATE_TRANSITION`; 422 |
| `GET /v1/organizations/{org_id}/audit-events` | `limit`, `cursor`, `action` (optional) | `200` page of `AuditEventOut` | 404; 403 (`owner`/`admin` only) |

`ApprovalOut`: `{"id","org_id","run_id","step_id","version_id","assigned_role","state","summary","expires_at","decided_by","decided_at","decision_comment","created_at"}`.
`AuditEventOut`: `{"id","org_id","actor_user_id","actor_type","action","target_type","target_id","request_id","redacted_metadata","created_at"}`.

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P7-T01 | test_approval_roles | `reviewer` can decide `assigned_role="reviewer"`, denied (`403`) on `"admin"` or `"owner"`; `operator` and `viewer` denied (`403`) on all approvals; `admin` can decide `"reviewer"` and `"admin"`, denied on `"owner"` |
| P7-T02 | test_approvals | Support-ticket workflow pauses at `approve` step: run state is `WAITING_APPROVAL`, lease is cleared (`lease_owner IS NULL`), and `approval_requests(PENDING)` is created with redacted summary |
| P7-T03 | test_approvals | Approving (`decision="approve"`) transitions approval to `APPROVED`, transitions run to `QUEUED`, emits `RunResumeRequested`, worker executes downstream `crm` HTTP step and finishes `SUCCEEDED` |
| P7-T04 | test_approvals | Rejecting (`decision="reject"`) transitions approval to `REJECTED` and run to `FAILED` (`error_code="APPROVAL_REJECTED"`); downstream `crm` HTTP step is **never** called |
| P7-T05 | test_approval_races | **Approval race:** two reviewers concurrently POST decisions (`approve` and `reject`) to the same pending approval → `asyncio.gather` returns one `200` and one `409 INVALID_STATE_TRANSITION`; DB has a single winner |
| P7-T06 | test_approval_races | **Permission revocation before decision:** user has `reviewer` role when approval is created, is demoted to `viewer` before deciding → `POST /decisions` returns `403 FORBIDDEN` |
| P7-T07 | test_approvals | Expired approval (`expires_at <= now()`): `POST /decisions` returns `409 INVALID_STATE_TRANSITION`; sweeper marks approval `EXPIRED` and run `FAILED` (`APPROVAL_EXPIRED`) |
| P7-T08 | test_approval_races | **Cancel vs approval:** cancelling a `WAITING_APPROVAL` run marks both the run and the pending `approval_requests` row `CANCELLED`; subsequent `POST /decisions` returns `409` |
| P7-T09 | test_audit_events | Every mutating action writes an `audit_events` row with `request_id` and redacted metadata; `UPDATE` or `DELETE` on `audit_events` fails in PostgreSQL with `P0002` |
| P7-T10 | test_audit_events | `GET /v1/organizations/{org_id}/audit-events` returns `200` for `owner`/`admin`, `403` for `operator`/`reviewer`/`viewer`, `404` for non-member |

## Frontend
- `ApprovalsPage` (`/orgs/:orgId/approvals`): filterable by state (default `PENDING`), shows `summary`, `assigned_role`, `expires_at` countdown, and "Approve" / "Reject" buttons (disabled with explanation if user's role rank is below `assigned_role`).
- `ApprovalBanner` on `RunDetailPage`: when `run.state === "WAITING_APPROVAL"`, displays the pending approval card inline with Approve/Reject actions.
- `AuditEventsPage` (`/orgs/:orgId/audit`): visible to `owner`/`admin`, paginated table of audit events.
- Frontend tests: `P7-F01` renders pending approvals and disables Approve/Reject for insufficient role; `P7-F02` submitting decision updates status and handles 409 conflict; `P7-F03` `ApprovalBanner` appears on `WAITING_APPROVAL` run.

## Labs (`docs/lab-notes/phase-07.md`)
1. **Simultaneous reviewer race:** fire 10 concurrent decision requests against one approval ID; confirm 1 succeeds (`200`) and 9 return `409`.
2. **Cancel vs step completion race:** trigger `POST /v1/runs/{id}/cancel` while a step is in flight; confirm monotonic terminal state and accurate `tool_effects` + `audit_events` records.

## Verification commands
```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P7-T01…T10 and P7-F01…F03 pass.
- [ ] Labs 1–2 recorded; Phase 7 PDF built.

## Agent brief
**Do:** evaluate role permissions against the live `memberships` row inside the decision transaction. **Don't:** allow updating or deleting `audit_events` rows from application code. **Stop and report** if any mutating endpoint from Phases 2–7 is missing an `audit_events` entry.
