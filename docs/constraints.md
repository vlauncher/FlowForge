# Engineering Constraints & Quality Targets

## 1. Technical Stack Constraints
- **Language / Runtime:** Python 3.14 (strict typing, asyncio for I/O, separate worker processes for execution).
- **Web Framework:** FastAPI with Pydantic v2 validation and explicit ASGI error handling.
- **Database & ORM:** PostgreSQL as the canonical source of truth, SQLAlchemy 2 async engine (`AsyncSession`), Alembic for controlled forward/backward migrations.
- **Background Execution:** Celery workers + RabbitMQ message broker with a Transactional Outbox pattern (no dual-write races, no reliance on ephemeral `BackgroundTasks`).
- **Frontend:** React 19 + TypeScript + Vite single-page application with TanStack Query owning asynchronous server state.
- **Packaging:** Reproducible lockfiles via `pip-tools` and Docker Compose for all backing services.

## 2. Model & External Provider Constraints
- **OpenRouter Free Tier Constraints:**
  - Hard platform rate limits: **20 Requests Per Minute (RPM)** and **50 Requests Per Day (RPD)** (expandable to 1,000/day after $10 lifetime credit purchase).
  - Model identifiers are strictly guarded: only models ending in `:free` or `openrouter/free` are permitted; paid fallbacks are refused by code.
  - Automated CI test suites and the 30-case evaluation harness run against `FakeLLM` to maintain 100% offline determinism and avoid quota exhaustion.
  - Upstream 429 rate limits must be respected with exponential backoff and `Retry-After` adherence.

## 3. Capacity & Project Scope
- Solo developer portfolio project with ~12–18 hours/week focused effort over 10 distinct phases.
- Architectural design prioritizes modular monolith architecture: single repository, strict internal boundaries, separate deployable processes (API, Worker, Scheduler).

## 4. Provisional Non-Functional Targets (Hypotheses to Measure)
The following targets are engineering hypotheses to be benchmarked in Phase 10 under controlled conditions:
- **API Latency:** 99% of local staging API requests under 250 ms at a defined 50-concurrent-client synthetic load (excluding asynchronous job execution time).
- **Durability:** Every accepted run is persisted to PostgreSQL and the transactional outbox before returning HTTP `202 Accepted`.
- **Fault Recovery:** 100% recovery of runs interrupted by abrupt worker process termination (`SIGKILL`) with zero duplicate committed external effects.
- **Tenant Isolation:** Zero data leaks or cross-tenant reads/writes across all endpoints (verified by automated BOLA matrix regression tests).
