# Phase 5 Lab Notes: Reliability, HTTP Tool Adapter, and Recovery

## Lab 1: Unrecoverable Tool Ambiguity & Safe Halting

### Objective
Demonstrate how the FlowForge `tool_effects` ledger protocol prevents duplicate side effects when upstream write operations time out ambiguously. We compare:
1. FlowForge non-idempotent handling (`provider_supports_idempotency: false`).
2. Naive automatic retry without ledger protection.
3. Provider idempotency key deduplication (`provider_supports_idempotency: true`).

### Experimental Setup
A mock upstream HTTP endpoint `/v1/charge` increments a global charge counter when invoked. After incrementing the counter, the server sleeps past the configured `timeout_seconds` (10s), dropping the connection or raising a `ReadTimeout` to the caller.

### Procedure & Results

| Strategy | Engine Configuration | Upstream Invocations | Side Effect Counter | Final Run State | Explanation |
|---|---|---|---|---|---|
| **FlowForge Safe Halt** | `effect: "write"`, `provider_supports_idempotency: false` | 1 | 1 | `FAILED` (`TOOL_EFFECT_AMBIGUOUS`) | Upon encountering a `ReadTimeout`, FlowForge marks `tool_effects.state = 'AMBIGUOUS'`. Because the provider does not support replay deduplication, the engine halts the workflow without sending a second POST, preventing duplicate billing. |
| **Naive Retry (Unprotected)** | Standard retry loop with no idempotency checks | 2 | 2 | `FAILED` / `SUCCEEDED` | The second request sends a duplicate charge to the upstream server, causing double-billing and data corruption. |
| **FlowForge Idempotency Replay** | `effect: "write"`, `provider_supports_idempotency: true` | 2 | 1 | `SUCCEEDED` | The engine injects header `Idempotency-Key: {run_id}:{step_id}` on all attempts. Upstream recognizes the duplicate key and deduplicates the side effect. |

### Conclusion
Recording `tool_effects(INTENDED)` prior to socket opening and recording `AMBIGUOUS` on ambiguous write timeouts is mathematically necessary to avoid split-brain duplicate side effects when integrating with non-idempotent legacy APIs.

---

## Lab 2: Worker Kill & Crash Recovery Mid-Workflow

### Objective
Verify that killing a worker mid-execution does not cause duplicate external side effects when the workflow is recovered by the sweeper and resumed by a subsequent worker.

### Procedure
1. Define a 2-step HTTP write workflow:
   - `step_1`: `POST /v1/customers` (creates customer record in external CRM).
   - `step_2`: `POST /v1/charges` (charges the customer).
2. Start Worker 1. Worker 1 claims the run, commits `tool_effects(step_1, COMMITTED, ref='cus_111')`, and completes `step_1`.
3. Worker 1 process is abruptly terminated (simulated crash, `kill -9` equivalent) before executing `step_2`.
4. Database lease for Worker 1 expires (`lease_expires_at < now()`).
5. Run the background sweeper loop (`sweep_stale_and_delayed_runs`).
6. Start Worker 2. Inspect executed network requests and database state.

### Observations & Verification
- **Sweeper Detection:** The sweeper identified the stale lease on `workflow_runs` (`wr.state = 'RUNNING' AND wr.lease_expires_at < now()`) via `SELECT ... FOR UPDATE OF wr SKIP LOCKED` and enqueued an outbox event `RunResumeRequested`.
- **Worker 2 Reclamation:** Worker 2 reclaimed the run using atomic state transition rule **R3**, advancing `attempt_epoch` from 1 to 2.
- **Side Effect Deduplication:** When Worker 2 reached `step_1`, it queried the `tool_effects` ledger, found `state == 'COMMITTED'`, skipped the external HTTP socket call completely, populated the step context from `response_summary`, and proceeded directly to `step_2`.
- **Execution Counts:**
  - `POST /v1/customers`: **1** invocation.
  - `POST /v1/charges`: **1** invocation.
- **Terminal State:** Workflow run finished in state `SUCCEEDED` with both step outputs present in `workflow_runs.context`.
