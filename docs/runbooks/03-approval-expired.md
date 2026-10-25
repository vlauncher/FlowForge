# Runbook 03: Approval Expired Triage & Recovery

## 1. Symptom & Alert
- **Alert**: `FlowForgeApprovalExpiredSpike`
- **PromQL**:
  ```promql
  sum(rate(flowforge_approvals_total{state="EXPIRED"}[15m])) > 5
  ```
- **Symptoms**: Workflows waiting on human intervention unexpectedly transition to `FAILED` with error code `APPROVAL_EXPIRED`. End users or operations teams report unattended action requests timing out.

## 2. Impact
- **Severity**: Low-Medium (P3).
- **Blast Radius**: Runs requiring approval are safely terminated to prevent stale or unvetted actions from executing past business SLAs. No data corruption or double executions occur.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Rate of approval requests by state (PENDING, APPROVED, REJECTED, EXPIRED)
sum(rate(flowforge_approvals_total[1h])) by (state)
```

### PostgreSQL Diagnosis Queries
```sql
-- List expired approvals in the last 24 hours with associated workflow run
SELECT
    ar.id AS approval_id,
    ar.org_id,
    ar.run_id,
    ar.step_id,
    ar.created_at,
    ar.expires_at,
    wr.state AS run_state,
    wr.error_code
FROM approval_requests ar
JOIN workflow_runs wr ON wr.id = ar.run_id
WHERE ar.state = 'EXPIRED'
  AND ar.updated_at >= NOW() - INTERVAL '24 hours'
ORDER BY ar.expires_at DESC;

-- Identify average pending duration before expiration
SELECT
    org_id,
    AVG(EXTRACT(EPOCH FROM (expires_at - created_at))) AS configured_ttl_seconds,
    COUNT(*) AS expired_count
FROM approval_requests
WHERE state = 'EXPIRED'
GROUP BY org_id;
```

## 4. Containment & Safe Recovery Steps
1. **Determine if Re-run or Retry is Required**:
   Review workflow definition and business context with the workflow owner. If the underlying business action is still valid:
2. **Re-trigger Workflow Run**:
   Workflow runs that reached terminal `FAILED` via `APPROVAL_EXPIRED` cannot be mutated directly (state machine invariant). Trigger a fresh run with identical inputs:
   ```bash
   curl -X POST "http://localhost:8000/v1/workflows/${WORKFLOW_ID}/runs" \
     -H "Authorization: Bearer ${API_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"inputs": {...}}'
   ```
3. **Adjust Step Timeout Window**:
   If the default approval timeout (e.g., 3600s / 1 hour) is insufficient for human review:
   Update the workflow draft definition to increase `timeout_seconds` on the approval step and publish a new version.
4. **Notify Approver Team**:
   Ensure notification channels (Slack, email, webhook) for pending approvals are delivering alerts to designated reviewers.

## 5. Escalation & Prevention
- **Escalation**: Escalate to Customer Success if business-critical SLA was breached.
- **Prevention**:
  - Implement reminder notifications at 50% and 80% of approval timeout expiration.
  - Review designated approval group routing so requests do not languish on inactive personnel.
