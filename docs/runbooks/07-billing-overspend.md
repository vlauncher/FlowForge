# Runbook 07: Billing Overspend & Budget Exhaustion

## 1. Symptom & Alert
- **Alert**: `FlowForgeOrgBudgetExhausted` or `FlowForgeOverspendDetected`
- **PromQL**:
  ```promql
  flowforge_org_budget_usage_ratio > 0.95
  ```
- **Symptoms**: New workflow runs or AI steps for an organization are rejected with HTTP 402 `PAYMENT_REQUIRED` or error code `BUDGET_EXHAUSTED`.

## 2. Impact
- **Severity**: Medium (P3).
- **Blast Radius**: Isolated strictly to the offending organization (multi-tenant boundary preserved). Other tenants continue normal operations unimpeded.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Committed budget usage micro-USD per organization
sum(flowforge_budget_committed_micro_usd) by (org_id)

# Budget reservation rejection count
sum(rate(flowforge_budget_rejections_total[15m])) by (org_id)
```

### PostgreSQL Diagnosis Queries
```sql
-- Audit organization current budget, committed spend, and active reservations
SELECT
    o.id AS org_id,
    o.name,
    o.budget_limit_micro_usd,
    COALESCE(u.committed_spend, 0) AS committed_spend,
    COALESCE(r.reserved_spend, 0) AS reserved_spend,
    (COALESCE(u.committed_spend, 0) + COALESCE(r.reserved_spend, 0)) AS total_obligated,
    o.budget_limit_micro_usd - (COALESCE(u.committed_spend, 0) + COALESCE(r.reserved_spend, 0)) AS remaining_budget
FROM organizations o
LEFT JOIN (
    SELECT org_id, SUM(cost_micro_usd) AS committed_spend
    FROM usage_records
    GROUP BY org_id
) u ON u.org_id = o.id
LEFT JOIN (
    SELECT org_id, SUM(amount_micro_usd) AS reserved_spend
    FROM budget_reservations
    WHERE state = 'RESERVED'
    GROUP BY org_id
) r ON r.org_id = o.id
WHERE o.id = '<OFFENDING_ORG_ID>';

-- Identify expensive runs or recursive loops in the organization
SELECT
    run_id,
    SUM(cost_micro_usd) AS total_run_cost,
    COUNT(*) AS records_count
FROM usage_records
WHERE org_id = '<OFFENDING_ORG_ID>'
  AND created_at >= NOW() - INTERVAL '24 hours'
GROUP BY run_id
ORDER BY total_run_cost DESC
LIMIT 10;
```

## 4. Containment & Safe Recovery Steps
1. **Audit for Stale Budget Reservations**:
   If runs crashed before settling budget, release orphaned reservations:
   ```sql
   UPDATE budget_reservations
   SET state = 'RELEASED',
       released_at = NOW()
   WHERE org_id = '<OFFENDING_ORG_ID>'
     AND state = 'RESERVED'
     AND created_at < NOW() - INTERVAL '1 hour';
   ```
2. **Contact Tenant Administrator**:
   Inform the organization billing contact of quota exhaustion and provide usage breakdown by workflow.
3. **Temporarily Raise or Adjust Budget Limit**:
   If authorized by billing or support contract:
   ```sql
   UPDATE organizations
   SET budget_limit_micro_usd = budget_limit_micro_usd + 50000000, -- Add $50.00
       updated_at = NOW()
   WHERE id = '<OFFENDING_ORG_ID>';
   ```
4. **Halt Runaway Loops**:
   If an infinite workflow or bug caused the spend surge, disable the workflow draft or publish version immediately:
   ```sql
   UPDATE workflows
   SET is_active = FALSE,
       updated_at = NOW()
   WHERE id = '<RUNAWAY_WORKFLOW_ID>'
     AND org_id = '<OFFENDING_ORG_ID>';
   ```

## 5. Escalation & Prevention
- **Escalation**: Escalate to Finance / Account Executive if tenant requests custom invoice arrangement.
- **Prevention**:
  - Send proactive notification webhooks at 75% and 90% budget utilization.
  - Require workflow validation to enforce max loop iteration limits.
