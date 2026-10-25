# Phase 9 Lab Notes: Security Hardening, Webhook Signatures & Concurrent Budgets

**Date:** 2026-10-25  
**Environment:** Linux (x86_64), Python 3.14.4, PostgreSQL 16 (Docker container), RabbitMQ 3.13 (Docker container)  
**Author:** FlowForge Core Engineering Team  

---

## 1. Executive Summary

Phase 9 implements comprehensive security hardening across the entire FlowForge stack:
1. **SSRF & DNS-Rebinding-Safe Egress Transport:** Validation against 15 blocked CIDR ranges, strict port allowlisting (443, 8443), single-resolution IP pinning with TLS SNI preservation, and disabling HTTP redirects (`follow_redirects=False`).
2. **Two-Phase Token Budget Reservation & Settlement:** Pessimistic row-level locking (`SELECT ... FOR UPDATE` on `organizations`) prevents concurrent over-allocation races. Tokens are reserved (`RESERVED`) prior to model invocation, then settled (`SETTLED`) from verified `usage_records` or released (`RELEASED`) on failure.
3. **HMAC-SHA256 Webhook Ingestion:** Public webhook endpoints authenticate callers via constant-time HMAC comparison with a ±300s timestamp tolerance window and signature-based replay deduplication (`webhook:{trigger_id}:{sig}`).
4. **Secret Rotation:** Programmatic and API rotation of credentials with AES-256-GCM authenticated encryption.
5. **Sliding-Window Rate Limiter:** Middleware throttling login brute-forcing (10/min), signup spam (5/hr), and user quotas (300/min).
6. **BOLA / IDOR Defense:** Enforced multi-tenant isolation where any cross-tenant resource access strictly returns `404 Not Found`.

---

## 2. Lab 1: SSRF & DNS Rebinding Egress Defense

### 2.1 Threat Vector Matrix

Attackers attempting to exploit workflow tool invocation steps (`http_request`) to access internal infrastructure, cloud instance metadata (`169.254.169.254`), container interfaces, or internal microservices employ multiple evasion techniques.

We tested 6 distinct bypass vectors against `app/infrastructure/http_tool/egress.py`:

| Vector ID | Attack Payload / Technique | Target Destination | Defense Mechanism | Observed Outcome |
|---|---|---|---|---|
| **V1** | Decimal IP Notation | `https://2130706433/` (`127.0.0.1`) | `parse_ip_literal` parses integer format and tests against `BLOCKED_NETWORKS` | **BLOCKED** (`EGRESS_BLOCKED`) |
| **V2** | IPv6-mapped IPv4 | `https://[::ffff:169.254.169.254]/` | `is_ip_blocked` inspects `ip.ipv4_mapped` and checks against link-local CIDR | **BLOCKED** (`EGRESS_BLOCKED`) |
| **V3** | Open HTTP 302 Redirect | `302 -> http://169.254.169.254/latest/meta-data/` | HTTPX client strictly configured with `follow_redirects=False` | **NOT FOLLOWED** (Status 302 preserved) |
| **V4** | Dual A-Record (Multi-IP DNS) | `93.184.216.34` + `10.0.0.1` | Loop validates *every* resolved IP address in the DNS answer; any private IP rejects request | **BLOCKED** (`EGRESS_BLOCKED`) |
| **V5** | TOCTOU DNS Rebinding | DNS returns Public IP on check, Metadata IP on connect | `validate_and_pin_url` resolves DNS exactly once and connects to pinned IP `https://93.184.216.34:443/` | **PINNED** (Single DNS call, zero rebind window) |
| **V6** | Non-Standard Ports | `https://api.example.com:6379/` (Redis port) | Port allowlist strictly restricted to `{443, 8443}` | **BLOCKED** (`EGRESS_BLOCKED`) |

### 2.2 Empirical Lab Execution Log

```text
--- LAB 1: SSRF & DNS Rebinding Defense ---
Vector 1: Decimal IP blocked: True
Vector 2: IPv6-mapped metadata blocked: True
Vector 3: HTTP 302 redirect not followed: True
Vector 4: Dual A-record containing private IP blocked: True
Vector 5: DNS rebinding pinned to validated IP: True
Vector 6: Non-standard port 6379 blocked: True
```

---

## 3. Lab 2: Concurrent Budget Exhaustion Race

### 3.1 Hypothesis

Without atomic concurrency control, $N$ simultaneous workflow executions could concurrently observe `committed_spend < budget_limit`, causing all $N$ executions to proceed and over-spend the organization's allocated budget by up to $N \times \text{step\_cost}$.

Under the FlowForge two-phase reservation algorithm:
1. Every reservation acquires `SELECT budget_limit_micro_usd FROM organizations WHERE id = :org_id FOR UPDATE`.
2. The current sum of `SETTLED` spend and active `RESERVED` budget is aggregated inside the lock.
3. If `committed + reserved + step_cost > limit`, the reservation is immediately rejected with `402 BUDGET_EXCEEDED`.
4. Exactly $\lfloor \text{budget\_limit} / \text{step\_cost} \rfloor$ runs should be permitted to reserve, and all remaining runs must fail.

### 3.2 Experimental Setup

- **Organization Budget Limit:** `15,000` micro-USD.
- **Configured LLM Token Price:** `1,000` micro-USD per 1,000 tokens.
- **Step Token Ceiling:** `max_tokens = 500`.
- **Estimated Step Reservation Cost:**
  $$\text{cost} = \left\lfloor \frac{(500 + 1000) \times 1000}{1000} \right\rfloor \times 2 = 3{,}000\ \mu\text{USD}$$
- **Concurrent Invocations:** 20 parallel coroutines launched simultaneously via `asyncio.gather`.

### 3.3 Empirical Lab Execution Log

```text
--- LAB 2: Concurrent Budget Exhaustion Lab ---
Concurrent requests: 20
Successes: 5 (reserved 15000 µUSD)
BudgetExceeded: 15
Total reserved: 15000 µUSD (limit: 15000 µUSD)
In-budget constraint held: True
```

### 3.4 Findings

- Exactly 5 runs succeeded ($5 \times 3{,}000 = 15{,}000\ \mu\text{USD}$).
- Exactly 15 runs were immediately failed with `BUDGET_EXCEEDED` (non-retryable).
- At no point during the execution race did total committed + reserved exceed $15{,}000\ \mu\text{USD}$.
- The pessimistic locking strategy eliminates TOCTOU races under high concurrency.

---

## 4. Lab 3: Webhook Replay & Idempotency Protection

### 4.1 Methodology

Webhook triggers (`POST /v1/triggers/webhooks/{trigger_id}`) were subjected to three adversarial scenarios:
1. **Tampered Payload:** Modification of a single byte in the JSON payload invalidated the HMAC-SHA256 signature, resulting in `401 WEBHOOK_SIGNATURE_INVALID`.
2. **Expired Timestamp:** A request with a timestamp 600s in the past was rejected with `401 WEBHOOK_REPLAY`.
3. **Duplicate Delivery:** A duplicate request within the 300s window with identical payload and signature returned `202 Accepted` with header `Idempotency-Replayed: true` and created **zero** additional runs.

---

## 5. Verification Checklist

- [x] P9-T01: SSRF validator rejects blocked IP ranges, non-HTTPS schemes, forbidden ports.
- [x] P9-T02: DNS rebinding and dual A-record private IP defense verified.
- [x] P9-T03: HTTP 302 redirects to internal endpoints strictly not followed.
- [x] P9-T04: Webhook HMAC-SHA256 signature and timestamp tolerance verified.
- [x] P9-T05: Webhook replay deduplication verified.
- [x] P9-T06: Concurrent budget race condition verified.
- [x] P9-T07: Login rate limiting (11th attempt within 1 minute returns 429) verified.
- [x] P9-T08: Comprehensive BOLA matrix across all endpoints verified (100% 404).
- [x] P9-F01: Frontend creates webhook trigger and displays URL and curl snippet.
- [x] P9-F02: Frontend rotates credential secret and displays updated `rotated_at`.
- [x] STRIDE + OWASP threat model committed in `docs/threat-model.md`.
