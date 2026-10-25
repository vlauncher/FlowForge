# Runbook 01: Provider 429 Storm & Circuit Breaker Open

## 1. Symptom & Alert
- **Alert**: `FlowForgeCircuitBreakerOpen` or `FlowForgeUpstreamRateLimited`
- **PromQL**:
  ```promql
  sum(rate(flowforge_circuit_breaker_trips_total[5m])) by (provider) > 0
  ```
  or
  ```promql
  sum(rate(flowforge_llm_requests_total{status="429"}[5m])) / sum(rate(flowforge_llm_requests_total[5m])) > 0.20
  ```
- **Symptoms**: Workflow runs executing AI steps stall or transition to `FAILED` with error code `RATE_LIMIT_EXCEEDED` or `UPSTREAM_UNAVAILABLE`. Circuit breaker for provider (e.g. `openrouter`) trips to `OPEN` state.

## 2. Impact
- **Severity**: High (P2).
- **Blast Radius**: All workflow runs utilizing the affected LLM provider or external HTTP host. Runs pause retries or fail depending on retry policy. In-flight runs may be requeued with exponential backoff.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Provider 429 error rate per provider over the last 15m
sum(rate(flowforge_llm_requests_total{status="429"}[5m])) by (provider)

# Circuit breaker state (0 = closed, 1 = half-open, 2 = open)
flowforge_circuit_breaker_state{provider="openrouter"}
```

### PostgreSQL Diagnosis Queries
```sql
-- Count runs currently blocked or failed by provider 429 in the last 1 hour
SELECT
    error_code,
    COUNT(*) AS affected_runs,
    MIN(updated_at) AS first_seen,
    MAX(updated_at) AS last_seen
FROM workflow_runs
WHERE state IN ('FAILED', 'QUEUED')
  AND error_code IN ('RATE_LIMIT_EXCEEDED', 'UPSTREAM_UNAVAILABLE', 'PROVIDER_RATE_LIMITED')
  AND updated_at >= NOW() - INTERVAL '1 hour'
GROUP BY error_code;

-- Identify top organizations affected
SELECT
    org_id,
    COUNT(*) AS run_count
FROM workflow_runs
WHERE error_code = 'RATE_LIMIT_EXCEEDED'
  AND updated_at >= NOW() - INTERVAL '1 hour'
GROUP BY org_id
ORDER BY run_count DESC
LIMIT 10;
```

## 4. Containment & Safe Recovery Steps
1. **Verify Circuit Breaker State**:
   Inspect whether the circuit breaker has tripped to prevent upstream request hammering:
   ```bash
   curl -s http://localhost:8000/metrics | grep flowforge_circuit_breaker
   ```
2. **Apply Upstream Throttling / Concurrency Limit**:
   Temporarily throttle concurrency or increase backoff multiplier in environment configuration:
   ```bash
   export WORKER_CONCURRENCY=5
   export LLM_RETRY_BACKOFF_FACTOR=2.5
   ```
3. **Failover / Model Degradation**:
   If the primary OpenRouter route or model (e.g., `openai/gpt-4o-mini`) is completely degraded, configure an alternate model alias in provider settings or swap credential secret to secondary account.
4. **Requeue Stalled Runs**:
   Once the provider stabilizes and circuit breaker resets to `HALF-OPEN` / `CLOSED`, requeue affected queued runs:
   ```sql
   UPDATE workflow_runs
   SET state = 'QUEUED',
       next_attempt_at = NOW(),
       updated_at = NOW()
   WHERE state = 'QUEUED'
     AND error_code = 'RATE_LIMIT_EXCEEDED'
     AND next_attempt_at > NOW();
   ```

## 5. Escalation & Prevention
- **Escalation**: Notify Platform Lead if 429 surge persists > 15 minutes. Contact provider support if tier quotas were not breached.
- **Prevention**:
  - Enforce per-org request rate limits before dispatching external LLM queries.
  - Implement dynamic hedging across multi-model providers.
  - Set alerts at 70% and 85% of provider tier RPM/TPM limits.
