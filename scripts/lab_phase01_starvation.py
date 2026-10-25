"""Phase 1 Break-it Lab: Event-Loop Starvation & Concurrency Benchmarking.

Demonstrates the catastrophic impact of executing synchronous blocking calls (e.g. `time.sleep()`,
blocking DB/network I/O, heavy CPU compute) directly inside an `async def` FastAPI route.
Compares:
1. Blocking async handler (`async def` with `time.sleep(1.0)`) stalling concurrent requests.
2. Proper async handler (`async def` with `await asyncio.sleep(1.0)`).
3. Threadpool-offloaded sync handler (`def` or `await asyncio.to_thread(...)`).
"""

import asyncio
import time

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health(request):
    return JSONResponse({"status": "ok", "ts": time.monotonic()})


async def bad_blocking_handler(request):
    # Synchronously blocks the event loop thread
    time.sleep(0.5)
    return JSONResponse({"status": "slept_bad"})


async def good_async_handler(request):
    # Cooperatively yields control so other tasks run concurrently
    await asyncio.sleep(0.5)
    return JSONResponse({"status": "slept_good"})


async def good_thread_handler(request):
    # Offloads blocking call to worker thread
    await asyncio.to_thread(time.sleep, 0.5)
    return JSONResponse({"status": "slept_thread"})


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/bad", bad_blocking_handler, methods=["GET"]),
    Route("/good", good_async_handler, methods=["GET"]),
    Route("/thread", good_thread_handler, methods=["GET"]),
]

app = Starlette(routes=routes)


async def run_scenario(name: str, slow_path: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Enqueue the slow task first
        slow_task = asyncio.create_task(client.get(slow_path))

        # 2. Enqueue the health probe immediately after
        t0 = time.monotonic()
        health_task = asyncio.create_task(client.get("/health"))

        # 3. Yield to the event loop by awaiting the health probe
        health_resp = await health_task
        health_latency_ms = (time.monotonic() - t0) * 1000

        await slow_task

        return health_latency_ms, health_resp.status_code


async def main():
    print("=" * 60)
    print("PHASE 1 LAB: ASYNCIO EVENT-LOOP STARVATION")
    print("=" * 60)

    # Baseline health check
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        t0 = time.monotonic()
        resp = await client.get("/health")
        base_ms = (time.monotonic() - t0) * 1000
    print(f"Baseline /health latency: {base_ms:.2f} ms (Status: {resp.status_code})")

    # Scenario 1: Bad blocking handler
    bad_ms, bad_status = await run_scenario("Blocking time.sleep() in async def", "/bad")
    print(f"Scenario 1 (Bad): /health latency during blocking call: {bad_ms:.2f} ms")

    # Scenario 2: Cooperative async handler
    good_ms, good_status = await run_scenario("Cooperative await asyncio.sleep()", "/good")
    print(f"Scenario 2 (Good): /health latency during cooperative async: {good_ms:.2f} ms")

    # Scenario 3: Offloaded thread handler
    thread_ms, thread_status = await run_scenario("Offloaded asyncio.to_thread()", "/thread")
    print(f"Scenario 3 (Thread): /health latency during offloaded sync: {thread_ms:.2f} ms")

    print("=" * 60)
    print("Summary:")
    print(f"  Event loop stall factor: {bad_ms / good_ms:.1f}x degradation")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
