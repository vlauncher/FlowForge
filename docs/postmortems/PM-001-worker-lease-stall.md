# Postmortem PM-001: Worker Lease Stall During Upstream LLM Provider Saturation

**Date:** 2026-10-25  
**Authors:** FlowForge Reliability Engineering Team  
**Status:** Complete / Action Items In Progress  
**Severity:** Sev-2 (Partial Execution Degradation)

---

## 1. Executive Summary
On October 25, 2026, between 14:10 UTC and 14:38 UTC (duration: 28 minutes), FlowForge experienced delayed execution on 42 workflow runs executing LLM generation steps. An upstream rate limit spike (HTTP 429) from the primary OpenRouter provider endpoint triggered unbounded exponential backoff retries within synchronous worker execution blocks. Because worker leases were renewed while waiting on upstream HTTP sockets, runs remained locked in `RUNNING` status without making forward progress, preventing the recovery sweeper from reclaiming the runs. No data was lost, no cross-tenant isolation was breached, and zero duplicate external side effects occurred.

---

## 2. Impact & Incident Metrics
- **Impacted Systems:** Background Execution Engine (`flowforge-worker`), Upstream LLM Connector.
- **Affected Customers:** 3 organizations running high-volume support ticket summarization workflows.
- **Run Statistics:**
  - Total runs initiated during window: 114
  - Runs delayed > 5 minutes: 42 (36.8%)
  - Runs failed permanently: 0
  - Duplicate external tool effects: 0 (guaranteed by `tool_effects` idempotency ledger).
- **Time to Detect (TTD):** 4 minutes (Prometheus alert `FlowForgeOldestQueuedRunAgeHigh` fired at 14:14 UTC).
- **Time to Mitigate (TTM):** 24 minutes (Circuit breaker tripped and worker pool restarted with tuned socket timeouts at 14:38 UTC).

---

## 3. Timeline (All times in UTC)
- **14:08**: OpenRouter upstream API experienced a 70% reduction in serving capacity for `openai/gpt-4o-mini`, returning HTTP 429 `Retry-After: 120`.
- **14:10**: 15 worker threads concurrently accepted LLM steps and entered sleep-retry loops respecting upstream `Retry-After`.
- **14:12**: Worker heartbeat loop continued to renew database leases (`lease_expires_at = now() + 30s`), keeping runs marked as `RUNNING` despite zero forward progress.
- **14:14**: Alert `FlowForgeOldestQueuedRunAgeHigh` (> 300s) fired in `#alerts-flowforge`. On-call engineer acknowledged.
- **14:20**: On-call engineer queried `workflow_runs` and observed all active workers occupied with frozen heartbeat timestamps.
- **14:25**: On-call engineer tripped the provider circuit breaker to `OPEN` manually, forcing immediate fallback rather than socket stalling.
- **14:32**: Worker containers were restarted with `LLM_STEP_TIMEOUT=45s`.
- **14:35**: Sweeper identified expired leases and enqueued `RunResumeRequested` events for all stalled runs.
- **14:38**: Stalled runs were reclaimed at `attempt_epoch = 2`; all 42 runs progressed to `SUCCEEDED` using fallback providers.
- **14:40**: System stabilized; incident closed.

---

## 4. Root Cause Analysis (5 Whys)
1. **Why were workflow runs delayed?**  
   Worker processes were blocked waiting for upstream OpenRouter responses.
2. **Why were the workers blocked?**  
   The HTTP client respected a 120-second `Retry-After` header within a single step attempt loop without an overarching step-level deadline.
3. **Why did the sweeper not reassign the stalled runs to other nodes?**  
   The background heartbeat loop was running asynchronously on the same worker process, renewing `lease_expires_at` even though the main execution coroutine was blocked.
4. **Why did the heartbeat continue when execution was stalled?**  
   The heartbeat task checked process liveness rather than step progress or forward progress deadlines.
5. **Why was the circuit breaker not triggered automatically earlier?**  
   The circuit breaker failure threshold evaluated HTTP 5xx errors but treated HTTP 429 as transient retryable rather than a trip-triggering failure mode.

---

## 5. What Went Well vs. What Went Wrong

### What Went Well
- **Zero Duplicate Side Effects:** Even though runs were resumed at `attempt_epoch = 2`, the tool-effects ledger verified `COMMITTED` states for pre-crash steps and prevented redundant third-party charges.
- **Clean Audit Trail:** All state transitions, retry attempts, and lease acquisitions were completely recorded in `audit_events`.
- **Alerting Response:** PagerDuty fired within 4 minutes of queue age threshold breach.

### What Went Wrong
- **Heartbeat False Positives:** Process-level heartbeat masked execution stall from the sweeper.
- **Circuit Breaker Gap:** 429 surges were not weighted heavily enough in circuit breaker open thresholds.
- **Operator Runbook Missing:** Runbook for upstream 429 storm had not yet been codified into standard operating procedures.

---

## 6. Action Items & Lessons Learned
| Action Item | Type | Owner | Target Date | Status |
|---|---|---|---|---|
| Configure circuit breaker to treat repeated 429s as trip conditions | Code | Platform | 2026-10-26 | Done (Phase 8/9) |
| Bind heartbeat renewal to active step timeout deadline | Code | Workers | 2026-10-27 | In Progress |
| Codify Runbook 01 (`docs/runbooks/01-provider-429-storm.md`) | Ops | SRE | 2026-10-25 | Done |
| Add per-step hard execution timeout (`default 60s`) | Architecture | Engine | 2026-10-28 | Done |
