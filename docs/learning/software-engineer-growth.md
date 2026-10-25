# How FlowForge Makes You a Better Software Engineer

## Competencies and where each phase trains them

| Competency | Phases | What you can explain afterwards |
|---|---|---|
| Requirements engineering | 1 | Functional vs non-functional, invariants, acceptance criteria |
| API design | 1, 4, 7 | HTTP semantics, `202`, idempotency keys, `409`, error format |
| Data modeling | 2, 3 | Constraints, indexes, MVCC, migrations, transaction boundaries |
| Reliability | 4, 5, 10 | Retries with jitter, leases, idempotency, recovery |
| Async/distributed systems | 4, 5 | At-least-once delivery, outbox, duplicates, reconciliation |
| Security | 6, 7, 9 | Tenant isolation, prompt injection, SSRF, secrets, least privilege |
| AI engineering | 6, 8 | Structured output, token budgets, evals, drift |
| Operations | 8, 9, 10 | SLIs/SLOs, traces, runbooks, restore drills |
| Frontend engineering | 1–10 | Auth tokens, polling, error states, accessibility |
| Communication | all | ADRs, trade-offs, design-review style write-ups |

## Mindset shifts this project trains
1. **From "it works" to "what happens when it fails."** Every phase has a break-it lab.
2. **From the happy path to invariants.** Say what must always be true, then enforce it in the database and tests.
3. **From trusting libraries to knowing guarantees.** Celery gives at-least-once delivery, so you design for duplicates.
4. **From using AI to supervising AI.** The roadmap's loop is PLAN → VERIFY → IMPLEMENT → TEST → EXPLAIN → REVIEW.

## Self-assessment rubric (0–3)
Domain reasoning, data correctness, reliability, security, performance, operations, communication. Aim for 2+ everywhere and 3 in your specialty. This is a self-test, not an employer assessment.

## Evidence you will own at the end
ADRs with rejected alternatives, a threat model, failing-then-passing regression tests, a kill-worker demo, a restore drill, a postmortem, and a case study. Describe them honestly as portfolio systems.
