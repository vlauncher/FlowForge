# Phase 10 Spec: Recovery Drills, Operations Runbooks, and Portfolio Evidence

Learning material: `flowforge.md` → Phase 10. Contracts: `spec/00-global.md` (all sections) and `flowforge.md` (Release Gates G1–G6). **Prerequisite:** Phase 9 done-when is green.

## Scope
End-to-end automated recovery drills (kill-worker mid-run recovery script, timed PostgreSQL backup & restore drill script, duplicate-event replay drill), reproducible synthetic load test (`50` concurrent clients against staging stack measuring p50/p95/p99 API latency and queue lag), all 8 operational runbooks (`docs/runbooks/`), 1 blameless postmortem (`docs/postmortems/PM-001-worker-lease-stall.md`), 10× traffic scaling proposal (`docs/architecture/10x-scaling-proposal.md`), complete C4 + ERD + sequence diagrams (`docs/architecture/diagrams.md`), engineering case study (`docs/case-study.md`), comprehensive `README.md`, and final verification of Release Gates G1–G6 + complete PDF generation.

## Steps
| ID | Step | Done when |
|---|---|---|
| P10-S01 | `scripts/drills/kill_worker_demo.py` and `tests/e2e/test_kill_worker_recovery.py`: launches a 2-step workflow, terminates worker process during step 1/2 transition, verifies sweeper + second worker recover the run to `SUCCEEDED` with 0 duplicate external effects | test and demo script pass |
| P10-S02 | `scripts/drills/backup_restore_drill.sh`: `pg_dump -Fc` of populated DB, restore with `pg_restore` into fresh `flowforge_restore_drill` DB, verifies row counts, checksums, and state invariants, records elapsed RTO | script exits 0 and writes `docs/lab-notes/restore-drill-report.md` |
| P10-S03 | `scripts/load/benchmark_api.py`: synthetic load benchmark (50 concurrent clients, warmup + 30 s measured window, mixes `POST /runs`, `GET /runs/{id}`, `GET /workflows`), outputs methodology (CPU, RAM, DB size, concurrency) and p50/p95/p99 latency report (`docs/lab-notes/load-benchmark-report.md`) | script runs and writes report |
| P10-S04 | Write all 8 operational runbooks in `docs/runbooks/` (detection, containment, safe replay, escalation) | all 8 files present and checked |
| P10-S05 | Write `docs/postmortems/PM-001-worker-lease-stall.md`, `docs/architecture/10x-scaling-proposal.md`, `docs/architecture/diagrams.md`, and `docs/case-study.md` | files complete |
| P10-S06 | Full-stack Playwright E2E test (`frontend/e2e/full_workflow.spec.ts`): signup → create org → create credential → create & publish support-ticket workflow → trigger run → inspect `WAITING_APPROVAL` → approve in UI → verify `SUCCEEDED` and usage dashboard | E2E test passes |
| P10-S07 | Write root `README.md` with architecture, quickstart, API examples, release gates G1–G6 evidence table, and honest portfolio caveats; build `FlowForge-Phase-10.pdf` and `FlowForge-Complete.pdf` | all checks and PDFs green |

## Files
```text
scripts/drills/{kill_worker_demo.py,backup_restore_drill.sh}
scripts/load/benchmark_api.py
tests/e2e/test_kill_worker_recovery.py
frontend/e2e/full_workflow.spec.ts
docs/runbooks/{01-provider-429-storm,02-stuck-running-task,03-approval-expired,04-webhook-signature-mismatch,05-queue-saturation,06-secret-compromise,07-billing-overspend,08-db-restore}.md
docs/postmortems/PM-001-worker-lease-stall.md
docs/architecture/{diagrams,10x-scaling-proposal}.md
docs/lab-notes/{phase-10,restore-drill-report,load-benchmark-report}.md
docs/case-study.md   README.md
```

## Drill & documentation contracts

### 1. Kill-Worker Recovery Drill (`scripts/drills/kill_worker_demo.py` & `P10-T01`)
1. Start a mock external tool server that counts requests per `Idempotency-Key` and notifies an event when `step_1` (`http_request`, `effect="write"`) commits.
2. Trigger a 2-step workflow (`step_1 -> step_2`).
3. Start Worker 1 (`lease_seconds=5` for fast test turnaround). As soon as `step_1` records `tool_effects(COMMITTED)` and before `step_2` finishes, forcefully kill/cancel Worker 1 (`SIGKILL` or task cancellation without releasing the lease).
4. Assert run is `RUNNING` with `lease_owner = worker_1`.
5. Wait for `lease_expires_at` to pass, run `sweeper.sweep_once()`, and start Worker 2.
6. Assert:
   - Worker 2 reclaims the run (`attempt_epoch = 2`).
   - Mock server received **exactly 1** call for `step_1` and **1** call for `step_2`.
   - Run reaches `state = 'SUCCEEDED'`.

### 2. Required Runbooks (`docs/runbooks/`)
Every runbook must contain 5 sections: **1. Symptom & Alert**, **2. Impact**, **3. Detection & Diagnosis Queries (exact SQL / PromQL)**, **4. Containment & Safe Recovery Steps**, **5. Escalation & Prevention**.
1. `01-provider-429-storm.md` (OpenRouter / upstream HTTP 429 surge & circuit breaker open)
2. `02-stuck-running-task.md` (`flowforge_oldest_queued_run_age_seconds` or expired lease diagnosis)
3. `03-approval-expired.md` (triage and manual retry policy after `APPROVAL_EXPIRED`)
4. `04-webhook-signature-mismatch.md` (clock skew vs secret rotation vs spoofing attack)
5. `05-queue-saturation.md` (outbox backlog growth & worker concurrency scaling)
6. `06-secret-compromise.md` (emergency credential rotation with `rotate_secrets.py` & audit query)
7. `07-billing-overspend.md` (`budget_reservations` audit, lowering org `budget_limit_micro_usd`)
8. `08-db-restore.md` (step-by-step `pg_dump` / `pg_restore` and outbox reconciliation after restore)

### 3. Release Gates Evidence Matrix (in `README.md` & `docs/case-study.md`)
Every gate G1–G6 must link to concrete files and test IDs in the repository:
| Gate | Required Evidence |
|---|---|
| G1 Specification | `docs/00-problem.md`, `spec/00-global.md`, `openapi.json`, `P1-T15` |
| G2 Data correctness | `alembic/versions/0001..0007`, `P2-T19..T23`, `P3-T11`, `P4-T10..T11`, `P7-T05` |
| G3 Security | `docs/threat-model.md`, `P2-T10`, `P6-T09`, `P7-T06`, `P9-T01..T08` |
| G4 Recovery | `docs/failure-recovery.md`, `P5-T06..T11`, `P10-T01`, `docs/lab-notes/restore-drill-report.md` |
| G5 Operations | `infra/observability/`, `docs/runbooks/01..08`, `docs/postmortems/PM-001-worker-lease-stall.md`, `P8-T02..T04` |
| G6 Communication | `docs/adr/ADR-001..005`, `docs/case-study.md`, `docs/architecture/10x-scaling-proposal.md` |

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P10-T01 | test_kill_worker_recovery | Automated kill-worker scenario completes `SUCCEEDED` with `attempt_epoch == 2` and zero duplicate external side effects |
| P10-T02 | test_kill_worker_recovery | Replay + cancel drill: duplicate outbox event delivery after run is `CANCELLED` or `SUCCEEDED` is a strict no-op |
| P10-T03 | test_kill_worker_recovery | Runbooks & gate evidence check: all 8 runbooks, 5 ADRs, threat model, postmortem, and case study exist and contain all required headings |
| P10-F01 | full_workflow.spec.ts | End-to-end Playwright flow from signup through human approval to `SUCCEEDED` run and usage verification passes |

## Labs (`docs/lab-notes/phase-10.md`)
1. Execute `scripts/drills/kill_worker_demo.py` and capture timeline logs.
2. Execute `scripts/drills/backup_restore_drill.sh` and record backup size, restore duration (RTO), and post-restore invariant verification query outputs.
3. Execute `scripts/load/benchmark_api.py` twice under identical conditions and record hardware, concurrency, p50/p95/p99 latencies, and error rate.

## Verification commands
```bash
docker compose up --build -d
alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/drills/kill_worker_demo.py
bash scripts/drills/backup_restore_drill.sh
python scripts/load/benchmark_api.py
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
.venv-docs/bin/python scripts/check_docs.py
.venv-docs/bin/python scripts/build_pdf.py --phase 10
.venv-docs/bin/python scripts/build_pdf.py --all
```

## Done when
- [ ] P10-T01…T03 and P10-F01 pass; all 3 drills/benchmarks executed and recorded.
- [ ] All 8 runbooks, postmortem, 10× scaling proposal, case study, and `README.md` completed.
- [ ] `FlowForge-Phase-10.pdf` and `FlowForge-Complete.pdf` built and verified.

## Agent brief
**Do:** run every drill and benchmark command and record the actual measured outputs (never invent benchmark latencies or RTO numbers). **Don't:** claim production commercial traffic or skip any of the G1–G6 checks. **Stop and report** if any release gate lacks passing test evidence.
