# Roadmap Analysis

Source: `01_FastAPI_AI_Agent_Workflow_Engineering_Roadmap.md` (edition 25 October 2026).

## What the product is
An organization-based service where users define **versioned directed workflows**, trigger runs, pause for **human approval**, call approved tools or LLMs, and inspect, retry and recover every step. Example: webhook ticket → classify → retrieve knowledge → draft reply → human approval → create CRM ticket → notify.

## Why it is hard (and why employers care)
| Problem | What forces you to solve it |
|---|---|
| Durable async execution | The API returns `202` and a worker runs steps later |
| State persistence | Runs survive process restarts |
| Crashes | A worker can die between a side effect and its commit |
| AI unreliability | Model output is untrusted and can be invalid |
| Multi-tenancy | Cross-organization data must never leak |
| Cost control | Token budgets prevent surprise bills |
| Observability | You must trace API → broker → worker → tool |

## Key invariants
1. Published workflow versions are immutable. Runs pin a version.
2. Run state machine: `QUEUED → RUNNING → WAITING_APPROVAL / SUCCEEDED / FAILED / CANCELLED`.
3. A job is durably accepted **before** the API acknowledges it.
4. Duplicate deliveries, restarts and retries must not duplicate committed side effects (where controllable). Remaining limits are documented, never hidden.
5. LLM output is untrusted. Tools have schemas, scopes and approval for irreversible actions.
6. Approvals are bound to run, step, version, actor and time window.

## Stack decisions
FastAPI + Pydantic, PostgreSQL + SQLAlchemy 2 async + Alembic, Celery + RabbitMQ, explicit state machine (not LangGraph for business effects), provider adapter for LLMs with a fake in tests, allowlisted HTTP adapters, OpenTelemetry + Prometheus + Grafana, pytest/Hypothesis/Testcontainers.

Our additions: **React + TypeScript + Vite** frontend, email/password JWT login, and **OpenRouter `:free` models** as the real provider.

## Scope boundaries
Out of scope: code execution on the server, arbitrary URL fetching, visual canvas, marketplace, unbounded agents.

## Release gates
G1 Specification, G2 Data correctness, G3 Security, G4 Recovery, G5 Operations, G6 Communication. Each needs evidence, not claims.

## Honest caveats
- Portfolio projects show senior-level behaviours; they do not confer a title.
- Latency targets are hypotheses to measure.
