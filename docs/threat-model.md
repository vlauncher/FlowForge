# FlowForge Threat Model & Security Architecture

**Document Version:** 1.0.0  
**Status:** Approved  
**Standards Covered:** STRIDE, OWASP API Security Top 10 (2023), OWASP Top 10 for LLM Applications (2025/2026).

---

## 1. System Architecture & Trust Boundaries

FlowForge is an enterprise AI workflow automation platform handling multi-tenant workflow definitions, third-party integration credentials, external API tool invocations, and LLM completions.

```text
[ External Webhook Senders ]       [ Users / Single Page App ]
            |                                  |
            | (HMAC-SHA256, HTTPS)             | (JWT Bearer, HTTPS)
            v                                  v
+-------------------------------------------------------------------+
| TRUST BOUNDARY 1: Edge & Ingress (Reverse Proxy, FastAPI)         |
|  - RequestIdMiddleware (X-Request-ID)                             |
|  - BodySizeLimitMiddleware (1 MB cap, RFC 9457 Problem Details)    |
|  - RateLimitMiddleware (10/min login, 5/hr signup, 300/min user)  |
|  - CORSMiddleware (Strict allowlist, no wildcards)                |
+-------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------+
| TRUST BOUNDARY 2: Application Core & Tenant Isolation             |
|  - Auth: Argon2id password hashing, JWT HS256, Refresh rotation   |
|  - RBAC: Live DB membership checks on every securable operation    |
|  - Egress: DNS-rebinding-safe SSRF validator with IP pinning       |
|  - Budget: Two-phase reservation & settlement (RESERVED->SETTLED)  |
+-------------------------------------------------------------------+
        |                                       |
        v                                       v
+-------------------------------+   +-------------------------------+
| TRUST BOUNDARY 3: Async Queue |   | TRUST BOUNDARY 4: Storage     |
|  - RabbitMQ transactional     |   |  - PostgreSQL (Multi-tenant)  |
|    Outbox publisher           |   |  - AES-256-GCM Credential     |
|  - Celery Worker cluster      |   |    Encryption at rest         |
|  - Sweeper & Heartbeats       |   |  - Append-only DB triggers    |
|  - Fencing token (epochs)     |   |    for immutable audit trail  |
+-------------------------------+   +-------------------------------+
        |                                       |
        v                                       v
+-------------------------------+   +-------------------------------+
| TRUST BOUNDARY 5: AI & LLM    |   | TRUST BOUNDARY 6: HTTP Tools  |
|  - Untrusted LLM output       |   |  - Pinned IP transport        |
|  - Schema-constrained parsing |   |  - 15 CIDR blocked ranges     |
|  - Token budget caps          |   |  - Strictly no redirects      |
+-------------------------------+   +-------------------------------+
```

---

## 2. STRIDE Threat Analysis Matrix

| Threat Category | Specific Threat Description | Architectural Countermeasure | Test Verification |
|---|---|---|---|
| **S**poofing | Attacker sends forged webhook events pretending to be upstream provider | HMAC-SHA256 signature verification over `timestamp.body` using encrypted credential secret; ±300s window | `tests/security/test_webhook_hmac.py` (`P9-T04`) |
| **S**poofing | Attacker forges JWT access tokens | HS256 signing with secret `>= 32 chars`; tokens verified for `iss`, `aud`, `exp`, signature | `tests/unit/test_security.py` (`P2-T01`) |
| **T**ampering | User alters published workflow version or step definition | DB trigger `forbid_published_version_update` enforces database-level immutability | `tests/integration/test_workflows.py` (`P3-T01`) |
| **T**ampering | Attacker tampers with historical audit logs | DB trigger `forbid_audit_events_mutation` rejects UPDATE and DELETE on `audit_events` | `tests/integration/test_audit_events.py` (`P7-T08`) |
| **R**epudiation | Operator denies approving sensitive irreversible side effect | Cryptographic audit trail records `actor_user_id`, timestamp, decision comment, and IP | `tests/integration/test_approvals.py` (`P7-T07`) |
| **I**nformation Disclosure | BOLA / IDOR cross-tenant data leak | All repository queries require `*, org_id: UUID`; foreign tenant IDs return `404 Not Found` | `tests/security/test_bola_matrix.py` (`P9-T08`) |
| **I**nformation Disclosure | Plaintext credentials leaked in logs, attempts, or traces | Recursive regex redaction (`password\|secret\|token\|authorization\|cookie`); credentials write-only | `tests/unit/test_redaction.py`, `tests/security/test_bola_matrix.py` |
| **D**enial of Service | Brute-force credential stuffing attacks on `/v1/auth/login` | Sliding window rate limiter enforces 10 requests / min per IP+email, returning `429` with `Retry-After` | `tests/security/test_rate_limits.py` (`P9-T07`) |
| **D**enial of Service | Algorithmic starvation / event loop blocking | Asyncio offloading (`asyncio.to_thread`), bounded pool sizes, request body cap (1 MB) | `tests/unit/test_body_limit.py`, `scripts/lab_phase01_starvation.py` |
| **D**enial of Service | Run concurrency or token budget exhaustion race | Pessimistic locking (`SELECT FOR UPDATE`), two-phase budget reservation (`RESERVED -> SETTLED`) | `tests/security/test_budget_concurrency.py` (`P9-T06`) |
| **E**levation of Privilege | Viewer attempts administrative mutation | Live database role resolution against `memberships`; no role claims baked into stateless JWTs | `tests/unit/test_permissions.py` (`P2-T02`) |
| **E**levation of Privilege | Automated bypass of human oversight for irreversible writes | Worker validates dominating approved `approval` step before executing irreversible HTTP tools | `tests/unit/test_approval_roles.py` (`P7-T04`) |

---

## 3. OWASP API Security Top 10 (2023) Mapping

| OWASP Top 10 | Vulnerability Description | FlowForge Control | Test Coverage |
|---|---|---|---|
| **API1:2023** | Broken Object Level Authorization (BOLA) | Every database query explicitly checks `org_id`. Attempting to access another org's ID returns `404 Not Found` | `tests/security/test_bola_matrix.py` (`P9-T08`) |
| **API2:2023** | Broken Authentication | Argon2id password hashing, rotating refresh tokens with automatic chain revocation upon token reuse | `tests/integration/test_auth_tokens.py` (`P2-T04`) |
| **API3:2023** | Broken Object Property Level Authorization | Pydantic V2 models with `extra="forbid"`; write-only credential secrets never serialized | `tests/integration/test_credentials.py` (`P5-T01`) |
| **API4:2023** | Unrestricted Resource Consumption | Per-org concurrency limit (5 runs), body size limiter (1 MB), token budget cap (µUSD), rate limits | `tests/security/test_budget_concurrency.py` (`P9-T06`) |
| **API5:2023** | Broken Function Level Authorization | RBAC matrix (`ROLE_PERMISSIONS`) enforced in service layer with live database role lookup | `tests/unit/test_permissions.py` (`P2-T02`) |
| **API6:2023** | Unrestricted Access to Sensitive Business Flows | Webhook replay deduplication (`idempotency_key = webhook:{trigger_id}:{sig}`), timestamp tolerance | `tests/security/test_webhook_hmac.py` (`P9-T05`) |
| **API7:2023** | Server-Side Request Forgery (SSRF) | DNS-rebinding-safe validator: blocks 15 CIDR ranges (RFC 1918, RFC 3927 metadata, IPv6 mapped), pins IP, strict `follow_redirects=False` | `tests/security/test_ssrf_egress.py` (`P9-T01`..`P9-T03`) |
| **API8:2023** | Security Misconfiguration | Non-root container execution (UID 10001), hardened Content-Security-Policy and CORS headers, production docs disabled | `infra/docker/api.Dockerfile`, `frontend/nginx.conf` |
| **API9:2023** | Improper Inventory Management | Committed `openapi.json` synchronized via automated CI drift check (`scripts/export_openapi.py`) | `tests/unit/test_openapi.py` (`P1-T02`) |
| **API10:2023** | Unsafe Consumption of APIs | Tool effects ledger (`tool_effects`) tracks external side-effects with circuit breaker protection | `tests/unit/test_circuit_breaker.py` (`P5-T03`) |

---

## 4. OWASP Top 10 for LLM / Agentic Applications Mapping

| OWASP LLM | Risk | FlowForge Control | Test Coverage |
|---|---|---|---|
| **LLM01:2025** | Prompt Injection | User inputs injected only via structured placeholders (`{{ inputs }}`); system prompts immutable on disk | `tests/unit/test_template_engine.py`, `ADR-005` |
| **LLM02:2025** | Sensitive Information Disclosure | Strict input/output redaction; credentials decrypted only in memory for tool execution and never passed to prompts | `tests/unit/test_redaction.py` (`P1-T05`) |
| **LLM04:2025** | Model Denial of Service | Two-phase budget reservation holds org lock and verifies spend before making model API calls | `tests/security/test_budget_concurrency.py` (`P9-T06`) |
| **LLM06:2025** | Excessive Agency | LLM output cannot invoke arbitrary tools; graph validator enforces static dependency DAG; irreversible writes require human approval | `tests/unit/test_graph_validator.py`, `tests/unit/test_approval_roles.py` |
| **LLM07:2025** | System Prompt Leakage | Prompts are stored in repo (`app/ai/prompts/*.yaml`), never exposed in API responses or database tables | `tests/unit/test_prompt_loader.py` |
| **LLM09:2025** | Misinformation / Overreliance | AI outputs validated with Pydantic / JSONSchema before advancing execution state | `tests/unit/test_structured_output.py` (`P6-T03`) |

---

## 5. Security Controls Summary

1. **Defense in Depth:** Every layer (Reverse Proxy, FastAPI, Service, Database Trigger) enforces constraints independently.
2. **Fail Closed:** Any ambiguous network error or DNS resolution failure aborts with `EGRESS_BLOCKED` or halts write operations in `AMBIGUOUS` state.
3. **Pessimistic Concurrency:** Budget reservations and execution quotas hold row-level exclusive locks (`FOR UPDATE`) to defeat TOCTOU race conditions.
