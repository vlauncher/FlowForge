# FlowForge: Complete Learn-and-Build Plan (Phases 1–10)

**What this file is.** The single, all-in-one plan. For each phase it holds the concepts, the reasons behind every decision, the build checklist, acceptance criteria, labs, sources, growth mapping, self-test and definition of done. At the end of each phase you build that phase's PDF (see "Per-phase PDFs" below).

**Product.** A multi-tenant AI agent and durable workflow automation platform: versioned directed workflows, asynchronous runs, human approval, allowlisted tools and LLM steps, full audit and recovery.

**Source roadmap:** `01_FastAPI_AI_Agent_Workflow_Engineering_Roadmap.md` (25 Oct 2026).
**Stack:** FastAPI, Pydantic v2, PostgreSQL, SQLAlchemy 2 async, Alembic, Celery + RabbitMQ, OpenTelemetry, Prometheus/Grafana, React + TypeScript + Vite, email/password JWT login, OpenRouter `:free` models, `pip` + `pip-tools`.

> **Honesty notes.** Latency and cost numbers are hypotheses to measure. Source status is labelled `checked` (confirmed through a web search of official/standards pages on 2026-10-25, not read page by page) or `to read` (taken from the roadmap, not yet opened). Portfolio systems show senior-level behaviour. They do not confer a job title.

## How to work every phase
1. Read the phase section and its sources.
2. Write story cards and acceptance tests first (Given/When/Then, at least one negative).
3. Implement in small commits, one behaviour per commit.
4. Run the gate commands yourself.
5. Do the break-it lab, write the ADR, record what really happened in the progress log.
6. Answer the self-test without notes or AI. If you can't, the phase isn't done.
7. Build the phase PDF.

## Standard gate commands
```bash
ruff check . && ruff format --check . && mypy app
pytest                                  # unit + integration (real PostgreSQL via Docker)
alembic upgrade head                    # on an empty database (from Phase 2)
cd frontend && npm run lint && npx tsc --noEmit && npx vitest run
```

## Per-phase PDFs
```bash
.venv-docs/bin/python scripts/build_pdf.py --phase 1     # docs/pdf/FlowForge-Phase-01.pdf
.venv-docs/bin/python scripts/build_pdf.py --all         # docs/pdf/FlowForge-Complete.pdf
```
A phase PDF contains: the phase section from this file (concepts, decisions, tasks, labs, sources, self-test) and the shared reference (glossary, release gates). Run it when the phase's done-when list is green.

## Target layout (grow it, don't create empty folders)
```text
app/{main.py, api/v1/, core/, modules/, domain/, application/, infrastructure/, workers/}
alembic/versions/   tests/{unit,integration,e2e,security,load}/
frontend/src/       docs/   scripts/   compose.yaml   .github/workflows/
requirements.in -> requirements.txt (pip-tools)   .env (git-ignored)
```

## Overview & Agent-Executable Specifications

- **Global Binding Specification (DDL, State Machines, Error Catalog, Security, Config):** [`spec/00-global.md`](spec/00-global.md)

| # | Phase | Build Spec | Main deliverable | Gate |
|---|---|---|---|---|
| 1 | Foundations and Discovery | [`spec/phase-01.md`](spec/phase-01.md) | Skeleton API + UI shell, PRD, state diagram, CI | G1 Specification |
| 2 | Data Layer and Tenancy | [`spec/phase-02.md`](spec/phase-02.md) | Auth, orgs, workflows, versions, migrations | Cross-tenant tests |
| 3 | Workflow Definition and Validation | [`spec/phase-03.md`](spec/phase-03.md) | Schema, DAG validator, publish | Invalid graphs rejected |
| 4 | Durable Execution Core | [`spec/phase-04.md`](spec/phase-04.md) | Run API (202), outbox, worker claim | Duplicate-delivery test |
| 5 | Reliability and Recovery | [`spec/phase-05.md`](spec/phase-05.md) | HTTP tool adapter, retries, sweeper | Crash and 503 tests |
| 6 | AI Steps | [`spec/phase-06.md`](spec/phase-06.md) | OpenRouter adapter, fake, structured output | Invalid-output tests |
| 7 | Approvals, RBAC and Audit | [`spec/phase-07.md`](spec/phase-07.md) | Approvals, roles, audit trail | Approval race test |
| 8 | Evaluation and Observability | [`spec/phase-08.md`](spec/phase-08.md) | 30-case eval, traces, dashboards | Baseline report |
| 9 | Security Hardening and Deployment | [`spec/phase-09.md`](spec/phase-09.md) | SSRF defense, secrets, quotas, CI scans | G3 Security |
| 10 | Proof, Operations and Portfolio | [`spec/phase-10.md`](spec/phase-10.md) | Kill-worker demo, restore drill, case study | G4, G5, G6 |

```mermaid
flowchart LR
  P1[1 Foundations] --> P2[2 Data+Tenancy] --> P3[3 Definitions] --> P4[4 Durable execution]
  P4 --> P5[5 Reliability] --> P6[6 AI steps] --> P7[7 Approvals] --> P8[8 Eval+Observability]
  P8 --> P9[9 Security+Deploy] --> P10[10 Proof+Portfolio]
```

---

## Phase 1: Foundations and Discovery
**Roadmap week 1 · ~12–18 h.**

### Objective
Fix what the system must guarantee, and build the thinnest running skeleton that proves the toolchain. Every later phase (outbox, workers, approvals) depends on the invariants written here.

### Concepts to learn
- **Functional vs non-functional requirements.** Functional: "a user can trigger a run." Non-functional: "99% of requests under 250 ms at 50 concurrent clients" (a hypothesis to measure).
- **Invariants.** Rules that always hold, e.g. "a published version is immutable." Tests, constraints and state machines enforce them later.
- **Acceptance criteria (Given/When/Then).** Turns a vague feature into a testable statement.
- **Modular monolith.** One deployable codebase with strict internal modules; API, worker and scheduler run as separate processes.
- **Dependency injection (`Depends`).** Handlers receive collaborators instead of creating them, which enables `app.dependency_overrides` in tests.
- **Typing and validation.** mypy checks types statically. Pydantic validates untrusted data at runtime at the boundary.
- **asyncio vs processes.** `async def` runs on one event-loop thread, so a blocking call stalls every request. `def` handlers run in a threadpool but the GIL stops CPU parallelism. Durable or CPU work belongs in a worker process. Concurrency is interleaving, parallelism is simultaneous execution.
- **HTTP semantics.** `202` for queued work, `409` for conflicting transitions, `404` (not `403`) for another tenant's object so existence isn't leaked. Errors use Problem Details (RFC 9457, `application/problem+json`: `type`, `title`, `status`, `detail`, `instance`) plus a stable `code` and `request_id`. RFC 9457 obsoletes RFC 7807 and keeps the core fields.
- **Frontend:** a client generated from OpenAPI keeps types honest; CORS needs an exact origin allowlist (never `*` with credentials); TanStack Query owns server state.

### Design patterns
| Pattern | Where | Why |
|---|---|---|
| Layered / ports and adapters | `api → application → domain → infrastructure` | Business rules never depend on HTTP or SQL |
| Dependency injection | `Depends(get_settings)` | Swappable, testable collaborators |
| Application factory | `create_app()` | Tests build an app without a socket |
| Settings object | `app/core/config.py` | One typed place for config; secrets stay in env |

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| FastAPI + Pydantic | Flask, DRF | Typed contracts, auto OpenAPI, native async | Docs/code drift |
| Modular monolith | Microservices | No scaling or ownership reason for network boundaries | Premature distributed complexity |
| PRD + invariants first | Code first | State/concurrency bugs come from unstated rules | Rework after a wrong state machine |
| `pip` + `pip-tools` lock | Unpinned installs | Reproducible installs | Dependency drift |
| Ruff + mypy | No static checks | Catch bug classes early | Type/style errors in review |
| App factory + overrides | Global app | Test isolation | State leaking between tests |
| Problem Details | Ad hoc JSON | Stable codes clients can branch on | Stack-trace leaks, inconsistent errors |
| React + Vite + TS | Next.js, Vue | Simple SPA against a separate API | Over-framework for an admin UI |

### Build tasks
- [ ] `docs/00-problem.md`, `constraints.md`, `risks.md`
- [ ] Run state diagram `QUEUED → RUNNING → WAITING_APPROVAL / SUCCEEDED / FAILED / CANCELLED`, with the actor per transition
- [ ] `app/main.py` with `create_app()`, `app/core/config.py` settings, `GET /health`, `GET /ready`
- [ ] Problem Details handlers, `X-Request-ID` middleware, CORS allowlist
- [ ] `pyproject.toml`, `requirements.in` → `requirements.txt`, ruff, mypy, pytest, pre-commit
- [ ] `frontend/` Vite + React + TS shell: health page, generated API client, lint, `tsc`, Vitest
- [ ] CI workflow; exported `openapi.json` committed

### Acceptance
- Given the app runs, when `GET /health`, then `200 {"status":"ok"}`.
- Given a request without `X-Request-ID`, then the response carries a generated one.
- Given an unknown route, then Problem Details `404` with no stack trace.
- Given invalid input, then `422` with field errors in the Problem Details shape.
- Negative: a CORS request from a non-allowlisted origin is not granted.

### Break-it labs
1. Add `async def` with `time.sleep(5)`, call `/health` meanwhile, measure the stall, move the work out.
2. Override settings with `dependency_overrides` and prove it doesn't leak into the next test.
3. Raise an unhandled exception and confirm no stack trace in the response.

### Sources
| Source | Type | Status | Takeaway |
|---|---|---|---|
| FastAPI: Concurrency and async/await | Official docs | checked | `async def` for awaitable I/O, `def` in a threadpool |
| FastAPI: Background Tasks | Official docs | checked | In-process, lost on restart, not for durable work |
| FastAPI: Testing | Official docs | to read | Test client, dependency overrides |
| RFC 9457 Problem Details | IETF standard | checked | Standard error body, obsoletes RFC 7807 |
| OpenAPI Specification | Standard | to read | Machine-readable contract |

### How this makes you a better engineer
Requirements engineering (turning features into invariants and testable criteria); reading concurrency docs critically instead of assuming "async is fast"; the ADR habit; quality gates that make later change safe.

### Self-test
1. Why does a blocking call in `async def` hurt unrelated requests?
2. Why is `BackgroundTasks` wrong for a workflow engine, and what replaces it?
3. Name three FlowForge invariants and the layer enforcing each.
4. Why `404` instead of `403` for another tenant's object?
5. What does the app factory buy you in tests?
6. Authentication vs authorization?
7. Why Pydantic if mypy checks types?

### Done when
- [ ] Acceptance tests and the CORS negative test pass.
- [ ] Gate commands are green in CI.
- [ ] State diagram and invariants reviewed, and you can teach them back.
- [ ] ADR-001 (modular monolith) written.
- [ ] Event-loop starvation lab measured.

---

## Phase 2: Data Layer and Tenancy
**Roadmap week 2.**

### Objective
Persist organizations, users and workflows safely, and make tenant isolation a property of the data layer, not a hope.

### Concepts to learn
- **SQL constraints** (PK, FK, unique, check, composite unique) as the last line of defence for invariants.
- **Indexes**: B-tree, composite order, partial indexes; read `EXPLAIN (ANALYZE, BUFFERS)`. Index `(org_id, created_at DESC)` for tenant lists.
- **MVCC and isolation.** PostgreSQL readers don't block writers. Read Committed allows lost updates and non-repeatable reads; Repeatable Read and Serializable add protection and can raise serialization failures you must retry. Write skew exists even under snapshot isolation.
- **Transactions.** Keep them short. Never hold row locks across a network call.
- **SQLAlchemy 2 async.** One `AsyncSession` per concurrent task or request; never share it. Implicit lazy I/O is forbidden in async, so load relations explicitly.
- **Alembic discipline.** Inspect generated SQL, never auto-sync production, use expand → migrate/backfill → contract.
- **Multi-tenancy** in a shared schema: `org_id` on every tenant table, filter on every query, default deny, `404` for foreign objects.
- **Repository pattern** and the unit of work, keeping SQL out of the domain.
- **Password hashing and JWT.** argon2 for passwords; short-lived JWTs with `exp`, `iss`, `aud`; production should use a real OIDC provider.
- **Cursor pagination** with deterministic sort and a maximum page size.
- **Time:** persist UTC instants.

### Design patterns
Repository, Unit of Work, Dependency Injection (`get_session`, `get_current_user`, `get_tenant_context`), Data Mapper (SQLAlchemy ORM).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| PostgreSQL as source of truth | Mongo, SQLite | Constraints, transactions, row locks, partial indexes | Business facts without integrity guarantees |
| Shared schema + `org_id` | Schema or DB per tenant | Simple operations for a solo project; constraints and tests enforce isolation | Operational overload; leaks are caught by tests |
| Object-level authorization | Route-level only | Route checks can't see which object | IDOR / cross-tenant reads |
| Session per request/task | Global session | Sessions aren't concurrency-safe | Corrupt state, hard-to-debug errors |
| Alembic reviewed migrations | `create_all` | Reproducible, reviewable schema changes | Silent schema drift |
| argon2 + short JWT | Plain/ fast hash; long-lived tokens | Slow hash resists cracking; short life limits theft | Credential and token theft impact |
| Cursor pagination | Offset | Stable under inserts, index-friendly | Duplicates/skips and slow deep pages |

### Build tasks
- [ ] Compose file with PostgreSQL; async engine and `session_factory`; session dependency
- [ ] Alembic baseline; tables `users`, `organizations`, `memberships` (unique `(org_id,user_id)`), `workflows`, `workflow_versions` (unique `(workflow_id,version)`)
- [ ] Signup/login (argon2, JWT), `get_current_user`
- [ ] Tenant-context dependency; all repositories take `org_id`
- [ ] `POST /v1/organizations/{org_id}/workflows`, paginated list
- [ ] Frontend: login, token handling, org switcher, workflow list

### Acceptance
- Org A user requests an org B workflow → `404`.
- No token → `401`; insufficient role → `403`.
- Migration runs on an empty DB; downgrade/upgrade cycle works.
- Duplicate `(org_id,user_id)` membership rejected by the database.

### Break-it labs
1. Share one `AsyncSession` across two concurrent tasks and observe the failure.
2. Reproduce a lost update at Read Committed, then fix it with `SELECT ... FOR UPDATE` or a version column.
3. Remove the `org_id` filter in one query and write the test that catches it.

### Sources
| Source | Type | Status |
|---|---|---|
| PostgreSQL: Transaction Isolation | Official docs | to read |
| PostgreSQL: Explicit Locking | Official docs | to read |
| SQLAlchemy: Asyncio ORM | Official docs | to read |
| Alembic documentation | Official docs | to read |
| Berenson et al. 1995, A Critique of ANSI SQL Isolation Levels | SIGMOD paper / MSR report | to read |
| OWASP API Security Top 10 (BOLA) | Security reference | to read |

### How this makes you a better engineer
You learn to put invariants into the database, to reason about concurrency anomalies by name, to treat ORMs as a convenience not a substitute for SQL, and to design tenant isolation that tests can prove.

### Self-test
1. What exact anomaly is a lost update, and name two ways to prevent it.
2. Why can't two coroutines share an `AsyncSession`?
3. What does `EXPLAIN (ANALYZE, BUFFERS)` tell you that a timing doesn't?
4. Why is the unique constraint better than a check in application code?
5. What is write skew, and does Repeatable Read stop it in PostgreSQL?
6. Why avoid remote calls while holding row locks?

### Done when
- [x] Cross-tenant, auth and constraint tests pass; migration from empty DB works.
- [x] ADR-002 (tenant isolation) written.
- [x] Labs done; you can explain isolation levels with an example.

---

## Phase 3: Workflow Definition and Graph Validation
**Roadmap week 3.**

### Objective
Define what a workflow is, reject invalid ones before they can run, and make published versions immutable.

### Concepts to learn
- **Directed graphs and DAGs**, reachability, cycle detection, topological sort (Kahn's algorithm or DFS colouring).
- **JSON Schema** (and Pydantic models) for the definition format, with a `schema_version` for evolution.
- **Immutability and versioning:** published `WorkflowVersion` rows never change; a checksum (hash of canonical JSON) detects tampering; runs pin a version.
- **Deterministic state machines:** pure `transition(state, event)` functions, tested without I/O.
- **Property-based testing (Hypothesis):** generate random graphs, assert invariants.
- **Type checking of connections:** step output types must match downstream input types.
- **Policy at validation time:** dangerous tool permissions are rejected when publishing.

### Design patterns
Strategy (step types), Factory/Registry (step type → validator), Value Object (immutable definitions), Specification (validation rules as composable checks).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Validate at publish | Validate at run time | Fail early with precise errors | Runs that can never finish |
| Immutable versions + checksum | Edit in place | Reproducible runs and audit | Behaviour changing under a running run |
| Pure domain validator | Validation in controllers | Testable, reusable by API and worker | Rules scattered across layers |
| DAG only (no cycles) in MVP | Loops | Bounded execution and simpler recovery | Unbounded runs, hard-to-reason recovery |
| Own state machine | LangGraph/Temporal | Business effects need an explicit ledger; keeps learning goals | Hidden framework semantics around side effects |

### Build tasks
- [ ] Definition schema: steps, edges, per-step input/output types, tool references, `schema_version`
- [ ] Pure validator: unreachable steps, cycles (report the step IDs), missing connections, type mismatches, forbidden tool permissions
- [ ] `POST /v1/workflows/{id}/versions`, `POST /v1/workflows/{id}/publish`
- [ ] Canonical JSON + SHA-256 checksum stored at publish
- [ ] Frontend: version editor with server-side validation errors displayed

### Acceptance
- A cyclic graph → `422` naming the offending steps.
- A published version can't be modified; editing creates version N+1.
- A graph with an orphan step is rejected.
- A step with a mismatched type connection is rejected.

### Break-it labs
1. Publish a cyclic graph, then a graph with an orphan step.
2. Hypothesis: generate random edge sets, assert `validate()` never raises unexpectedly and every accepted graph has a topological order.

### Sources
| Source | Type | Status |
|---|---|---|
| JSON Schema specification | Standard | to read |
| Pydantic v2 documentation | Official docs | to read |
| Hypothesis documentation | Official docs | to read |
| LangGraph learning materials | Vendor docs | to read |
| Garcia-Molina and Salem 1987, Sagas | SIGMOD paper | to read (applied in Phase 5) |

### How this makes you a better engineer
You learn to model a domain as data plus pure rules, to prove rules with property-based tests instead of hand-picked examples, and to choose a custom component over a framework with a written trade-off.

### Self-test
1. Why is a cycle a problem for the MVP, and how does your validator find it?
2. What does the checksum protect against?
3. Why should the validator not import FastAPI or SQLAlchemy?
4. What invariants did Hypothesis check?
5. When would you reach for LangGraph or Temporal instead?

### Done when
- [x] Validator unit and property tests pass; publish endpoint tests pass.
- [x] ADR-003 (custom state machine vs LangGraph/Temporal) written.

---

## Phase 4: Durable Execution Core
**Roadmap week 4.**

### Objective
Accept a run durably, execute it asynchronously, and survive duplicate messages and process crashes.

### Concepts to learn
- **Delivery semantics:** at-most-once, at-least-once, "exactly-once" as a goal reached by idempotent processing, not by trusting the broker.
- **Transactional outbox:** write state and an outbox event in one transaction; a publisher sends events later. This closes the gap between "DB committed" and "message sent."
- **Idempotency keys:** a unique `(org_id, idempotency_key)` makes a retried request return the original run.
- **Leases and heartbeats:** a worker claims a run for a time window and renews it; a stale lease allows takeover.
- **Conditional updates:** `UPDATE ... WHERE state='QUEUED'`; zero affected rows means someone else won.
- **`FOR UPDATE SKIP LOCKED`** for queue-like claiming.
- **Celery:** acks, late acknowledgement, retries; tasks may run multiple times.
- **RabbitMQ basics:** exchanges, queues, durability, acks, dead letters.
- **Ordering:** never assume in-order processing.

### Design patterns
Transactional Outbox, Idempotent Receiver, Competing Consumers, Lease, State pattern (domain transitions).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Outbox + publisher | Publish inside the request | No dual-write between DB and broker | Committed run never published, or published run never committed |
| Celery + RabbitMQ | `BackgroundTasks` | Separate process, durable queue, retries | Lost work on API restart |
| DB-constrained idempotency | In-memory dedupe | Survives restarts; race-safe via unique index | Duplicate runs from client retries |
| Lease + heartbeat | Fixed lock | Detects dead workers | Runs stuck `RUNNING` forever |
| Late ack | Early ack | Task is retried if the worker dies | Silent loss of in-flight work (at the cost of duplicates) |

### Build tasks
- [x] Tables `workflow_runs` (unique `(org_id,idempotency_key)`), `step_attempts` (unique `(run_id,step_id,attempt_no)`), `outbox_events` (migration `0003_runs_outbox`)
- [x] `POST /v1/workflows/{id}/runs`: insert `Run(QUEUED)` + outbox row in one transaction, return `202` with `run_id` and `status_url`
- [x] Outbox publisher process to RabbitMQ; mark `published_at` (`app/infrastructure/messaging/outbox_publisher.py`)
- [x] Celery worker: claim via conditional update with lease and heartbeat, run steps, record attempts, set terminal state (`app/workers/runner.py`)
- [x] `GET /v1/runs/{id}`, `GET /v1/runs/{id}/steps`, `GET /v1/organizations/{org_id}/runs`
- [x] Indexes: `(org_id,created_at DESC)`, `(state,next_attempt_at)`, partial index on unpublished outbox
- [x] Frontend: trigger-run form, polling status page (`TriggerRunModal`, `RunsListPage`, `RunDetailPage`)

### Acceptance
- Same `Idempotency-Key` twice → one run, same response.
- The run row exists before `202` is returned.
- Two workers can't both claim one run.
- The same message published twice → a single committed effect.

### Break-it labs
1. Crash after the outbox write but before publish; show the publisher recovers it.
2. Kill a worker after publish but before ack; show the duplicate is safe.
3. Publish the same message twice and count side effects until stable.

### Sources
| Source | Type | Status |
|---|---|---|
| Celery: Tasks (acks, retries) | Official docs | to read |
| RabbitMQ tutorials and reliability guide | Official docs | to read |
| Lamport 1978, Time, Clocks, and the Ordering of Events | CACM journal | to read |
| PostgreSQL explicit locking (`SKIP LOCKED`) | Official docs | to read |

### How this makes you a better engineer
You stop saying "exactly-once" and learn to design for duplicates; you reason about every crash point; you learn that guarantees live in database rows.

### Self-test
1. What data must be durable before the `202`?
2. Walk each crash point: before publish, after publish, before ack. What is observable, and what prevents duplication?
3. Which row constrains concurrent workers?
4. Why isn't "late ack" free?
5. How does a lease differ from a lock?

### Done when
- [ ] Duplicate-delivery and concurrent-claim tests are deterministic and green.
- [ ] ADR-004 (duplicate-delivery policy) written; crash scenarios documented.

---

## Phase 5: Reliability and Recovery
**Roadmap week 5.**

### Objective
Call external tools safely, retry the right things, and recover work abandoned by dead workers.

### Concepts to learn
- **Timeouts everywhere**; retry only idempotent or reconciled operations.
- **Exponential backoff with jitter**, `Retry-After` handling, bounded attempts, retry budgets.
- **Circuit breaker** (closed, open, half-open) and **bulkheads** to contain failure.
- **Retriable inference vs retriable side effects.** Re-asking a model is safe; re-sending an email is not.
- **Tool-effect ledger:** record intent and outcome per `(provider, idempotency_key)`.
- **Ambiguity after timeout:** the provider may have acted. Use provider idempotency keys or reconcile or involve a human.
- **Recovery sweeper/reconciler** for stale leases.
- **Cancellation semantics** and monotonic states; sagas and compensation.

### Design patterns
Retry, Circuit Breaker, Bulkhead, Saga/Compensation, Ledger, Reconciler (control loop).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Ledger with unique key | Trust retries | Stops duplicate external effects where controllable | Double charges/tickets |
| Jittered backoff | Fixed delay | De-synchronises clients | Retry storms |
| Allowlisted HTTP adapter | Generic `fetch_url` tool | Egress policy (finished in Phase 9) | SSRF |
| Separate sweeper | Rely on Celery retry | Handles dead leases the broker can't see | Runs stuck forever |
| Bounded attempts | Retry until success | Predictable cost and clear failure | Infinite loops, surprise bills |

### Build tasks
- [x] HTTP tool adapter: hostname allowlist, per-tool timeout, response-size cap, redacted credentials
- [x] `tool_effects` ledger table with unique `(provider, idempotency_key)`
- [x] Retry policy with backoff, jitter, `Retry-After`; circuit breaker per provider
- [x] Recovery sweeper for stale `RUNNING` runs
- [x] `POST /v1/runs/{id}/cancel`
- [x] Frontend: step timeline with attempts and failures

### Acceptance
- An upstream 503 retries a bounded number of times then ends in a clear `FAILED` with an error code.
- A killed worker's run resumes and doesn't repeat an effect already in the ledger.
- Cancel racing a completing step ends in exactly one defined terminal state.

### Break-it labs
1. Provider performs the action then times out. Classify each case: retry-safe, needs reconciliation, needs a human.
2. Kill the worker mid-run and watch the sweeper recover it.
3. Trip the circuit breaker with a failing fake provider.

### Sources
| Source | Type | Status |
|---|---|---|
| Garcia-Molina and Salem 1987, Sagas | SIGMOD paper | to read |
| Dean and Barroso 2013, The Tail at Scale | CACM journal | to read |
| Google SRE Book (handling overload, cascading failures) | Free book | to read |
| Celery task retry documentation | Official docs | to read |

### How this makes you a better engineer
You learn failure modes in a taxonomy (safe retry, ambiguous, compensatable), and you practise writing the failure diagram before the code.

### Self-test
1. Why can't you blindly retry a timed-out POST?
2. What does jitter fix?
3. When does a circuit breaker help, and when does it hurt?
4. What proves a run recovered correctly after a crash?
5. What can't be compensated?

### Done when
- [x] Crash, 503 and cancel-race tests are deterministic and green.
- [x] Failure diagram written; remaining exactly-once limits documented.

---

## Phase 6: AI Steps
**Roadmap week 6.**

### Objective
Add LLM-powered steps that stay safe when the model is wrong, slow, rate-limited or malicious input is present, using OpenRouter free models.

### Concepts to learn
- **LLM output is untrusted input.** Validate it like user input.
- **Structured output:** JSON schema, validation, capped retries, fallback or human review.
- **Token budgeting:** estimate before, record actual after; set max tokens.
- **Prompt injection** (direct and via retrieved or tool content) and **excessive agency.** The model never holds credentials; tools pass deterministic policy checks.
- **Adapter pattern:** one interface, many providers; a deterministic fake for tests.
- **OpenRouter specifics** (status: checked via search): model IDs ending in `:free` or the `openrouter/free` router cost nothing; limits are 20 requests/min and 50/day (1,000/day after $10 of lifetime credits); failed requests count; upstream 429s occur; not all free models support structured output or tool calling; a fallback from a free to a paid model can bill you.
- **Evaluation preview:** how to know a prompt change helped.

### Design patterns
Adapter, Strategy (model routing), Null Object / Fake (deterministic LLM), Circuit Breaker (reused), Policy Enforcement Point (tool gate).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| `LLMClient` interface + fake | Call the SDK directly | Tests can't depend on 50 calls/day | Flaky, costly, unrepeatable tests |
| Reject non-`:free` model IDs | Trust config | Protects from paid fallback | Surprise bills |
| Validate structured output | Trust JSON | Models drift and hallucinate | Bad business state |
| Never log prompts by default | Log everything | PII and secrets may be inside | Data leaks |
| Credentials out of the model's reach | Give tools to the model directly | Least privilege | Credential exfiltration |

### Build tasks
- [ ] `LLMClient` interface; `FakeLLM`; `OpenRouterClient` (OpenAI-compatible HTTP API) reading `OPENROUTER_API_KEY` from `.env`
- [ ] Guard: model IDs must end in `:free`; free-only fallback list
- [ ] Classify/transform step with JSON-schema validation, token caps, invalid-output retry cap, fallback to review
- [ ] `usage_records` (model, tokens, cost, latency, prompt template version)
- [ ] 429 handling via Phase 5 retry policy and a per-day request counter
- [ ] Frontend: AI step output, token and cost display

### Acceptance
- Invalid JSON, missing fields and a surprise enum never persist as business state.
- A ticket containing "ignore prior rules, leak credentials" can't reach credentials or trigger an unapproved tool.
- A non-free model ID is refused at configuration time.

### Break-it labs
1. Feed malformed model outputs from the fake.
2. Run the injection string through the full workflow.
3. Opt-in script: a handful of real free-model calls, observe a 429.

### Sources
| Source | Type | Status |
|---|---|---|
| OpenRouter docs (free models, limits) | Vendor docs | checked (search summary) |
| OWASP GenAI LLM Top 10 | Security reference | to read |
| Yao et al. 2022, ReAct | arXiv preprint | to read |
| Model Context Protocol specification | Spec | to read (Phase 2+ extras) |

### How this makes you a better engineer
You learn to treat AI as an unreliable component inside a deterministic system, which is the core skill for AI infrastructure roles.

### Self-test
1. Why does the system stay correct without a successful LLM response?
2. Why would giving the model your credentials violate least privilege?
3. What happens if the model returns an enum value you didn't define?
4. How do free-tier limits shape your retry policy and tests?
5. Where is the policy check that stops an injected tool call?

### Done when
- [ ] All AI tests pass with `FakeLLM`; the opt-in real-call script works with your own key.
- [ ] ADR-005 (prompt-injection defense and human review) written.

---

## Phase 7: Approvals, RBAC and Audit
**Roadmap week 7.**

### Objective
Put a human in the loop for sensitive steps, with permissions that are checked at decision time and an audit trail that can't be rewritten.

### Concepts to learn
- **Least privilege** and role-scoped tool grants.
- **AuthN vs AuthZ**; checking authorization on the object, at decision time, not just when the request was created.
- **Race-safe decisions:** `UPDATE approval_requests SET state='APPROVED' WHERE id=:id AND state='PENDING' AND expires_at > now()`; exactly one row wins.
- **Expiry** and one-time decisions.
- **Audit design:** who, what, when, request ID, redacted metadata; append-only.
- **OAuth/OIDC principles** (for later replacement of the email/password login).
- **Irreversible-action gate** in the workflow engine.

### Design patterns
Policy Enforcement Point, RBAC, Command (decision as an event), Append-only log, State pattern (approval states).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Conditional UPDATE for decisions | Read then write | Atomic, race-free | Two reviewers both "winning" |
| Recheck role at decision time | Trust the creation-time role | Roles change | Revoked users approving |
| Approval bound to run, step, version | Free-floating approvals | Stops reuse | Approving one thing and executing another |
| Append-only audit with redaction | Mutable logs | Evidence and privacy | Tampering, secret leakage |

### Build tasks
- [ ] `approval_requests` table; the approval step sets the run to `WAITING_APPROVAL` and schedules expiry
- [ ] `POST /v1/approvals/{id}/decisions` with role checks and `409` for already-decided
- [ ] Irreversible-tool gate requiring an approved request
- [ ] `audit_events` writer with request IDs and redaction
- [ ] Frontend: approval inbox, role-aware buttons, pending states

### Acceptance
- Two simultaneous decisions → exactly one succeeds, the other gets `409`.
- A reviewer whose role was removed after the request is denied.
- An expired approval is rejected and the run follows the expiry policy.

### Break-it labs
1. Approval race with two concurrent requests.
2. Cancel racing a step completion; define the monotonic result.

### Sources
| Source | Type | Status |
|---|---|---|
| OWASP API Security Top 10 | Security reference | to read |
| FastAPI OAuth2/JWT tutorial | Official docs | to read (learning only; production uses OIDC) |
| Pang et al. 2019, Zanzibar | USENIX ATC | to read (concepts only, not implemented) |
| NIST AI Risk Management Framework | Government guidance | to read |

### How this makes you a better engineer
You practise authorization as a property of data and time, and learn to prove a race condition is fixed by a deterministic test.

### Self-test
1. What proves a reviewer may approve now, given permissions changed?
2. Why a conditional UPDATE instead of read-then-write?
3. What goes in the audit log, and what must never?
4. How does expiry interact with cancellation?

### Done when
- [ ] Race, expiry and RBAC tests deterministic and green.
- [ ] Audit events present for every decision.

---

## Phase 8: Evaluation and Observability
**Roadmap week 8.**

### Objective
Measure whether the system and its AI behave well, and make a run visible end to end.

### Concepts to learn
- **Evaluation methodology:** a frozen, versioned dataset; metrics (pass rate, error types, latency, cost); judge criteria; avoiding test-set leakage; drift when prompts or models change.
- **SLIs and SLOs:** availability, latency, error rate, queue lag, max run age, domain correctness.
- **Distributed tracing:** spans, context propagation across the broker (inject/extract), sampling (Dapper ideas).
- **Structured logging** with correlation IDs and redaction.
- **Metrics:** counters, gauges, histograms; **cardinality** control; Prometheus scrape model; Grafana panels.
- **Retrieval/ranking basics** (only if a workflow needs grounded documents).

### Design patterns
Observer / Instrumentation, Context Propagation, Golden Dataset testing, Decorator (instrumentation wrappers).

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Frozen 30-case golden set | Ad hoc manual checks | Comparable before/after | Unnoticed regressions |
| Trace across broker | Per-process logs only | One run, one story | Hours of log archaeology |
| Queue lag and max run age metrics | HTTP latency only | The system is asynchronous | A healthy API hiding a stuck queue |
| Low-cardinality labels | `run_id` as a label | Protects Prometheus | Metric explosion |

### Build tasks
- [ ] 30-case golden set with dataset version and scoring script; baseline report (pass rate, errors, latency, cost)
- [ ] OpenTelemetry traces API → outbox → broker → worker → tool, propagating context
- [ ] JSON logs with request/run IDs and secret redaction
- [ ] Prometheus metrics and a Grafana dashboard (queue lag, max run age, outcomes)
- [ ] `GET /v1/usage`; frontend usage, cost and outcome dashboard

### Acceptance
- One run yields a single trace across API and worker.
- Changing the prompt or model produces a measurable difference on the frozen set.
- Dashboards reflect an injected failure.

### Break-it labs
1. Change a prompt and compare against the frozen baseline.
2. Stall the worker and watch queue-lag and max-run-age move.

### Sources
| Source | Type | Status |
|---|---|---|
| OpenTelemetry Python instrumentation | Official docs | to read |
| Sigelman et al. 2010, Dapper | Google technical paper | to read |
| Google SRE Book and Workbook (SLIs/SLOs) | Free books | to read |
| Lewis et al. 2020, RAG | arXiv/NeurIPS | to read |
| Liu et al. 2023, AgentBench | arXiv/ICLR | to read |

### How this makes you a better engineer
You learn to demand evidence before and after a change, and to instrument for questions you haven't asked yet.

### Self-test
1. Why a frozen dataset?
2. Which metric reveals a stuck queue when HTTP looks healthy?
3. How does trace context cross a message broker?
4. Why is a `run_id` label a bad idea?

### Done when
- [ ] Baseline report committed; trace and dashboard screenshots captured.

---

## Phase 9: Security Hardening and Deployment
**Roadmap week 9.**

### Objective
Close the known holes, bound resource use and make the deployment reproducible and safe.

### Concepts to learn
- **Threat modeling with STRIDE**; mapping threats to controls and tests.
- **OWASP API Top 10 and LLM/Agentic Top 10** as abuse-case generators.
- **SSRF:** hostname and IP validation (including redirects and DNS rebinding), blocked ranges (private, loopback, link-local, metadata), egress network policy.
- **Secrets:** encrypted references, rotation, never in logs or prompts.
- **Webhook security:** HMAC signatures, timestamp window, replay defense.
- **Resource bounds:** per-org concurrency, max steps/depth, tool timeout, output size.
- **Budget reservation and settlement** for concurrent AI spend.
- **Deployment:** non-root minimal images, health checks, graceful SIGTERM, connection pool sizing, expand/contract migrations, CI scans (dependencies, secrets, containers), frontend CSP and accessibility.

### Design patterns
Defense in depth, Fail-closed, Reservation/Settlement (two-phase budget), Secure defaults.

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Resolve then validate then connect to the pinned IP | Validate the hostname string only | DNS can change between check and use | DNS-rebinding SSRF |
| HMAC + timestamp window | Shared static token | Detects spoofing and replay | Webhook impersonation |
| Reserve budget before the call | Check after the call | Concurrent calls could all pass | Overspend |
| Non-root container, scans in CI | Default images | Smaller blast radius | Compromise escalation |

### Build tasks
- [ ] Egress validator and tests with redirects and private/metadata addresses
- [ ] Encrypted secret references, rotation procedure, signed webhook endpoint `POST /v1/triggers/webhooks/{trigger_id}`
- [ ] Per-org concurrent-run limit, step and depth caps, spend budget with reservation and settlement
- [ ] Production Compose, non-root images, health checks, SIGTERM handling
- [ ] CI: dependency audit, secret scan, container scan
- [ ] Frontend: CSP, token storage review, accessibility check
- [ ] `docs/threat-model.md`

### Acceptance
- Requests to internal IPs, link-local and metadata addresses are blocked, including via redirect.
- Replayed or stale webhook signatures are rejected.
- Concurrent AI steps never exceed the org budget.

### Break-it labs
1. Attempt SSRF through a redirect and a rebinding-style fake resolver.
2. Fire many concurrent AI steps at a tiny budget.

### Sources
| Source | Type | Status |
|---|---|---|
| OWASP GenAI LLM Top 10 and Agentic Top 10 | Security references | to read |
| OWASP Cheat Sheets (SSRF, secrets, logging) | Security references | to read |
| NIST SP 800-218 SSDF | Government standard | to read |
| GitHub Actions security | Official docs | to read |

### How this makes you a better engineer
You learn to attack your own system first, to turn each threat into a test, and to treat deployment as part of the design.

### Self-test
1. Why isn't hostname validation enough against SSRF?
2. How does a replay window work?
3. Why reserve then settle instead of check then spend?
4. Which STRIDE categories does the webhook endpoint face?

### Done when
- [ ] Security tests green; threat model complete; CI scans run.

---

## Phase 10: Proof, Operations and Portfolio
**Roadmap week 10.**

### Objective
Prove recovery, document operations, and present the system honestly.

### Concepts to learn
- **Failure drills:** kill a worker, disable the DB, delay the provider, fill the queue, replay duplicate events.
- **Backup and restore:** a restore drill with timing (RPO/RTO language).
- **Load testing discipline:** hardware, dataset, concurrency, warmup, duration, p50/p95/p99, error rate; numbers without method aren't evidence.
- **Runbooks:** detection, containment, safe replay, escalation.
- **Blameless postmortems** and a 10× change proposal.
- **Communication:** ADRs with rejected alternatives, a case study written like a design review.

### Design patterns
Chaos experiment, Runbook, Postmortem template, ADR.

### Why these decisions
| Decision | Rejected | Why | Failure prevented |
|---|---|---|---|
| Timed restore drill | Assume backups work | Recovery must be practised | Discovering a broken backup during an incident |
| Reproducible load method | One-off numbers | Credible, repeatable evidence | Unsupported claims |
| Honest case study | Marketing claims | Interview credibility | Overclaiming traffic or reliability |

### Build tasks
- [ ] Kill-worker demo with recovery evidence
- [ ] Replay and cancel tests; load test scripts and results with methodology
- [ ] Restore drill with measured time
- [ ] Runbooks: 429 storm, stuck `RUNNING`, approval expired, webhook signature mismatch, queue saturation, secret compromise, overspend, DB restore
- [ ] One simulated-incident postmortem; one 10× traffic proposal
- [ ] README, OpenAPI with examples, ERD, context/container/sequence diagrams, 5+ ADRs, case study, 2-minute demo and architecture walkthrough

### Acceptance
Each release gate G1–G6 has written evidence (see the shared section).

### Interview demo
Trigger run → show transitions → approve → kill worker → replay safely → show eval metrics and trace.

### Break-it labs
1. Run the full failure-drill set: kill a worker, stop the DB, delay the provider, fill the queue, replay duplicate events. Record the outcome of each.
2. Restore a backup into a fresh database and time it.
3. Run the load test twice under identical conditions and compare p50/p95/p99.

### Sources
| Source | Type | Status |
|---|---|---|
| Google SRE Book and Workbook (postmortems, incident response) | Free books | to read |
| Lamport 1978 (revisit for approval/cancel ordering) | CACM journal | to read |
| NIST AI RMF | Guidance | to read |

### How this makes you a better engineer
You learn to produce evidence, not assertions: drills, numbers with methodology, runbooks someone else can follow, and an honest account of limits.

### Self-test
1. What proves recovery after a killed worker?
2. What goes in a benchmark description?
3. What would you redesign at 10× load, and why?
4. Which claims in your résumé table can you back with a link and a test?

### Done when
- [ ] G4, G5, G6 evidence exists; demo recorded; the Phase 10 PDF built.

---

## Shared: Glossary
| Term | Meaning |
|---|---|
| Organization (tenant) | Owner of workflows, credentials, runs and budgets |
| WorkflowVersion | Immutable published definition; edits create a new version |
| Run / StepAttempt | One execution of a pinned version / one try of a step |
| Idempotency key | Token ensuring a repeated request has one effect |
| Outbox | Events written in the same transaction as state, published later |
| Lease / heartbeat | Time-limited claim on a run, renewed while alive |
| At-least-once delivery | A message may arrive more than once, so consumers are idempotent |
| Tool effect | An external side effect recorded in a ledger |
| Approval | Human decision bound to run, step, version, actor and time window |
| Invariant | A rule that must always hold |
| ADR | Architecture Decision Record |
| SLI / SLO | Measured indicator / target for it |
| Problem Details | RFC 9457 standard error body |
| SSRF | Server-side request forgery |
| MVCC | Multi-version concurrency control |

## Shared: Release gates
| Gate | Pass evidence |
|---|---|
| G1 Specification | PRD + tests define allowed and forbidden behaviour |
| G2 Data correctness | Tests fail on invalid transitions and races |
| G3 Security | Cross-tenant, unauthenticated and replay attacks denied |
| G4 Recovery | Kill worker/provider gives a correct outcome or a declared limit |
| G5 Operations | Traces, dashboards, restore and rollback documented |
| G6 Communication | ADRs show alternatives, assumptions, costs, evidence |

## Shared: Progress log
| Phase | Started | Finished | Notes / surprises |
|---|---|---|---|
| 1 | 2026-10-25 | 2026-10-25 | Fast skeleton bootstrap; doc check rules and ReportLab PDF toolchain operational. |
| 2 | 2026-10-25 | 2026-10-25 | Asyncpg connection pool requires NullPool in per-test event loops; SELECT FOR UPDATE required for last-owner safety; Keyset pagination benchmarks 33% faster with 58% lower cost than offset. |
| 3 | 2026-10-25 | 2026-10-25 | Strict dominators prevent undefined variable races in diamond graphs; 500 Hypothesis property tests verify acyclic invariants; DB trigger enforces published immutability. |
| 4 | 2026-10-25 | 2026-10-25 | Transactional outbox with SKIP LOCKED solves dual-write race; lease + fencing tokens (attempt_epoch) prevent zombie worker commit; asyncpg interval encoding requires datetime.timedelta. |
| 5 | 2026-10-25 | 2026-10-25 | Tool-effects ledger INTENDED/COMMITTED/AMBIGUOUS stops duplicate external side effects; bounded exponential backoff with full jitter & Retry-After; recovery sweeper rescues stale leases; cancel/retry state machine (R9-R11) verified. |
| 6 | 2026-10-25 | 2026-10-25 | Human-in-the-loop approvals, cryptographically tied to run/version/step, role-based authorization, sweeper auto-expiration, frontend review cards and state polling. |
| 7 | 2026-10-25 | 2026-10-25 | Multi-provider LLM integrations (OpenRouter, mock fallbacks), prompt template injection defenses via delimiters and schema validation, usage record tracking with micro-USD precision. |
| 8 | 2026-10-25 | 2026-10-25 | Full observability suite (Prometheus metrics, OpenTelemetry distributed tracing, Grafana alerts, sliding-window circuit breaker with half-open probe recovery). |
| 9 | 2026-10-25 | 2026-10-25 | Comprehensive security hardening: SSRF egress validator with 15 blocked CIDRs & IP pinning to prevent DNS rebinding, two-phase budget reservation with SELECT FOR UPDATE locks, HMAC-SHA256 webhooks, credential rotation API, BOLA security matrix. |
| 10 | 2026-10-25 | 2026-10-25 | Chaos failure recovery drills (kill-worker mid-step with zero duplicate side effects), automated PostgreSQL backup & restore drill (0.354s RTO), 50-client load benchmark (275 req/s at 0% error), 8 operational runbooks, postmortem PM-001, 10x scaling proposal, C4 diagrams, and portfolio case study. |
