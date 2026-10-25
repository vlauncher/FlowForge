# Runbook 04: Webhook Signature Mismatch & Ingestion Failures

## 1. Symptom & Alert
- **Alert**: `FlowForgeWebhookSignatureVerificationFailures`
- **PromQL**:
  ```promql
  sum(rate(flowforge_webhook_requests_total{status="401"}[5m])) > 1
  ```
- **Symptoms**: External webhook events are rejected with HTTP 401 `UNAUTHORIZED` or error detail `Invalid webhook signature` or `Signature timestamp expired`. Upstream workflows fail to trigger.

## 2. Impact
- **Severity**: Medium (P2).
- **Blast Radius**: External integrations (Stripe, GitHub, custom SaaS) cannot trigger downstream automation workflows. If legitimate, inbound events may be dropped if upstream sender lacks retry capability.

## 3. Detection & Diagnosis Queries

### PromQL
```promql
# Webhook ingest volume by status code
sum(rate(flowforge_webhook_requests_total[5m])) by (status)
```

### PostgreSQL Diagnosis Queries
```sql
-- Check audit logs for failed webhook authentication attempts
SELECT
    id,
    org_id,
    actor_type,
    action,
    entity_type,
    metadata,
    created_at
FROM audit_events
WHERE action = 'webhook_signature_rejected'
  AND created_at >= NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 50;

-- Verify webhook trigger status and associated credential
SELECT
    t.id AS trigger_id,
    t.org_id,
    t.workflow_id,
    t.state,
    t.credential_id,
    ic.provider,
    ic.updated_at AS credential_last_rotated
FROM triggers t
LEFT JOIN integration_credentials ic ON ic.id = t.credential_id
WHERE t.kind = 'webhook';
```

## 4. Containment & Safe Recovery Steps
1. **Differentiate Clock Skew vs Secret Rotation vs Spoofing Attack**:
   - Check request timestamp header `X-FlowForge-Timestamp` against host system clock. Tolerated drift window is ±300 seconds (5 minutes). If difference > 300s, sender NTP clock is desynchronized.
   - If timestamp is within bounds, compare signing secret in `integration_credentials` against provider settings. Was secret rotated recently without updating upstream provider?
   - If IP address does not match known provider egress CIDRs, treat as unauthorized probe or spoofing attempt.
2. **Synchronize Host NTP Clock**:
   ```bash
   timedatectl status
   sudo systemctl restart systemd-timesyncd
   ```
3. **Verify Signing Header Construction**:
   Ensure external sender constructs the HMAC payload strictly as:
   `f"{timestamp}.{raw_body_bytes.decode('utf-8')}"`
   and computes HMAC-SHA256 hex digest:
   `X-FlowForge-Signature: t={timestamp},v1={hex_digest}`
4. **Replay Dropped Events**:
   Request upstream provider webhook redelivery (e.g. Stripe Dashboard -> Webhooks -> Resend event) once keys and timestamps are aligned.

## 5. Escalation & Prevention
- **Escalation**: Escalate to Security Operations if high-volume signatures from unexpected IPs are detected.
- **Prevention**:
  - Always rotate webhook secrets with overlapping grace windows where both old and new signatures are temporarily verified.
  - Document HMAC verification curl examples in developer docs.
