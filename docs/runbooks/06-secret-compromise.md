# Runbook 06: Secret Compromise & Emergency Credential Rotation

## 1. Symptom & Alert
- **Alert**: `FlowForgeSecretCompromiseReported` or manual security incident declaration.
- **PromQL**:
  ```promql
  sum(rate(flowforge_credential_operations_total{operation="rotate"}[1h])) > 0
  ```
- **Symptoms**: An API key, webhook secret, or integration token stored in FlowForge was exposed in logs, public code repositories, or third-party breaches.

## 2. Impact
- **Severity**: Critical (P1).
- **Blast Radius**: Potential unauthorized egress actions or impersonation against external third-party APIs (Stripe, OpenRouter, GitHub) belonging to the compromised organization.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Credential access rate by organization
sum(rate(flowforge_credential_operations_total[15m])) by (org_id)
```

### PostgreSQL Diagnosis Queries
```sql
-- Audit all executions that accessed the suspected credential in the last 72 hours
SELECT
    te.id AS effect_id,
    te.org_id,
    te.run_id,
    te.step_id,
    te.provider,
    te.state,
    te.created_at,
    te.external_ref
FROM tool_effects te
JOIN workflow_runs wr ON wr.id = te.run_id
WHERE te.provider = '<PROVIDER_NAME>'
  AND te.org_id = '<COMPROMISED_ORG_ID>'
  AND te.created_at >= NOW() - INTERVAL '72 hours'
ORDER BY te.created_at DESC;

-- Review audit events for credential updates or rotation history
SELECT
    id,
    org_id,
    actor_id,
    action,
    entity_id,
    metadata,
    created_at
FROM audit_events
WHERE entity_type = 'integration_credential'
  AND org_id = '<COMPROMISED_ORG_ID>'
ORDER BY created_at DESC;
```

## 4. Containment & Safe Recovery Steps
1. **Revoke Upstream Key**:
   Immediately log into upstream vendor portal (e.g. Stripe / OpenRouter dashboard) and generate a new key. Do NOT delete the old key until step 2 is complete if zero-downtime cutover is required.
2. **Execute Emergency Rotation via CLI or API**:
   Use `scripts/rotate_secrets.py` to encrypt and store the replacement secret:
   ```bash
   python scripts/rotate_secrets.py \
     --org-id "<COMPROMISED_ORG_ID>" \
     --credential-id "<CREDENTIAL_ID>" \
     --new-secret "<NEW_SECRET_VALUE>"
   ```
   Or invoke the rotation API directly:
   ```bash
   curl -X POST "http://localhost:8000/v1/organizations/${ORG_ID}/credentials/${CRED_ID}/rotate" \
     -H "Authorization: Bearer ${API_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"new_secret": "sk_live_new_..."}'
   ```
3. **Deactivate Old Secret Upstream**:
   Revoke and destroy the compromised secret in the upstream provider portal.
4. **Invalidate In-Flight Workflows**:
   Cancel any currently running workflows using the old credential:
   ```sql
   UPDATE workflow_runs
   SET cancel_requested = TRUE,
       updated_at = NOW()
   WHERE org_id = '<COMPROMISED_ORG_ID>'
     AND state = 'RUNNING';
   ```

## 5. Escalation & Prevention
- **Escalation**: Notify Legal and Data Protection Officer if customer PII or financial accounts were exposed.
- **Prevention**:
  - Enforce secret rotation policies every 90 days.
  - Implement Git secret scanners (gitleaks / trufflehog) in CI pipelines.
  - Never allow raw credentials to be returned in API response bodies (FlowForge masks secrets as `sk_test_...abcd`).
