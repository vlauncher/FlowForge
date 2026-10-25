# Phase 1 Lab Notes: Event-Loop Starvation & Concurrency Benchmarks

## 1. Objective
Demonstrate experimentally how synchronous blocking operations within `async def` route handlers in FastAPI/Starlette freeze the single OS thread powering the `asyncio` event loop. Measure the latency degradation suffered by concurrent health check probes (`/health`), and verify remediation strategies.

---

## 2. Experimental Setup
- **Python Version:** 3.14.4
- **Framework:** Starlette / FastAPI ASGI
- **HTTP Client:** `httpx.AsyncClient` with `ASGITransport`
- **Lab Script:** `scripts/lab_phase01_starvation.py`

### Test Endpoints:
1. `GET /health`: Baseline probe returning `{"status":"ok"}`.
2. `GET /bad`: Anti-pattern endpoint executing synchronous `time.sleep(0.5)` directly inside `async def`.
3. `GET /good`: Standard async endpoint executing non-blocking `await asyncio.sleep(0.5)`.
4. `GET /thread`: Offloaded synchronous endpoint executing `await asyncio.to_thread(time.sleep, 0.5)`.

---

## 3. Execution & Measurements

| Scenario | Background Call | `/health` Probe Latency | Status | Event Loop Condition |
|---|---|---|---|---|
| Baseline | None | **0.50 ms** | 200 OK | Normal |
| **Scenario 1 (Bad)** | `time.sleep(0.5)` in `async def` | **501.14 ms** | 200 OK | **Starved / Blocked** (~1289x latency spike) |
| **Scenario 2 (Good)** | `await asyncio.sleep(0.5)` in `async def` | **0.39 ms** | 200 OK | Interleaved / Cooperative |
| **Scenario 3 (Thread)** | `await asyncio.to_thread(time.sleep, 0.5)` | **1.62 ms** | 200 OK | Worker thread offloaded |

---

## 4. Key Findings & Engineering Takeaways

1. **The Single-Thread Trap:**
   Because an ASGI application runs on an event loop driven by a single operating system thread, any blocking call (e.g. `time.sleep`, synchronous requests `requests.get()`, synchronous disk I/O, or CPU-intensive schema parsing) halts all coroutine processing. In production, this causes Kubernetes readiness/liveness probes to time out, triggering unnecessary pod restarts.

2. **Remediation Hierarchy:**
   - **Preferred:** Native non-blocking asynchronous libraries (e.g. `httpx.AsyncClient`, `asyncpg`, `aiofiles`).
   - **Acceptable for legacy/CPU sync tasks:** `asyncio.to_thread(...)` or declaring the route as standard synchronous `def endpoint(...)` so FastAPI dispatches it to the Starlette `anyio` worker threadpool.
   - **For durable or heavy compute:** Asynchronous workers via Celery / RabbitMQ.

3. **Production Policy for FlowForge:**
   - Strict ban on synchronous network libraries (`requests`, `urllib3`) in async routes.
   - All tool adapters (Phase 5) must use async HTTP clients with strict timeouts.
   - Heavy parsing (e.g., massive JSON schemas or cryptographic verification) must be evaluated for threadpool offloading.
