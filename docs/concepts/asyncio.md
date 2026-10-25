# Concept: asyncio, the event loop, and processes

**Definition.** `asyncio` runs many tasks on one thread by switching at `await` points. A task that never yields blocks all others.

**Failure it prevents (when used right).** Idle waiting on network or DB I/O wasting threads. **Failure it causes (when misused).** One blocking call freezing the whole API.

**Experiment.** `async def` endpoint with `time.sleep(5)`, hit `/health` meanwhile.

**Trade-offs.** Great for I/O concurrency, useless for CPU parallelism because of the GIL. Use processes (Celery workers) for CPU or durable work.

**In FlowForge.** The API stays on the event loop for short I/O. Run execution lives in worker processes so a slow LLM or tool call never blocks HTTP.

**Rules.** One `AsyncSession` per concurrent task (Phase 2). Never share it. Always set timeouts on outbound calls.
