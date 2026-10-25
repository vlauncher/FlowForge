# Phase 9 Spec: Security Hardening, Webhooks, Budgets, and Deployment

Learning material: `flowforge.md` → Phase 9. Contracts: `spec/00-global.md` (§3 tables `triggers`, `budget_reservations`; §7 errors; §8 API surface; §9 config; §10 security rules: egress CIDR blocklist, webhook HMAC, rate limits). **Prerequisite:** Phase 8 done-when is green.

## Scope
Migration `0007_triggers_budgets` (`triggers`, `budget_reservations`, and FK `workflow_runs.trigger_id -> triggers.id`), DNS-rebinding-safe SSRF egress validator with IP pinning and TLS SNI preservation, two-phase token budget reservation and settlement (`RESERVED → SETTLED | RELEASED`), HMAC-SHA256 signed webhook trigger endpoint with timestamp window and replay protection, secret rotation support, API rate-limiting middleware, STRIDE + OWASP threat model (`docs/threat-model.md`), frontend Content-Security-Policy and accessibility verification, and CI security scanning gates.

## Config additions (`Settings`)
`webhook_timestamp_tolerance_seconds: int = 300`, `rate_limit_enabled: bool = True`.

## Steps
| ID | Step | Done when |
|---|---|---|
| P9-S01 | Revision `0007_triggers_budgets` (`triggers`, `budget_reservations`, FK on `workflow_runs.trigger_id`) | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds |
| P9-S02 | `app/infrastructure/http_tool/egress.py`: DNS resolution, CIDR blocklist check (all 15 ranges in `spec/00-global.md` §10), port check (`443`, `8443`), and pinned-IP transport with TLS `sni_hostname` | unit + integration SSRF tests pass |
| P9-S03 | `app/modules/usage/budget.py`: two-phase `reserve_budget` and `settle_budget` / `release_budget` wired into `POST /v1/workflows/{id}/runs` and worker AI steps | concurrency budget tests pass |
| P9-S04 | `app/modules/triggers/{models,schemas,repository,service,router}.py`: `POST /v1/workflows/{id}/triggers` and `POST /v1/triggers/webhooks/{trigger_id}` (HMAC-SHA256 + timestamp + replay dedupe) | webhook integration tests pass |
| P9-S05 | Add secret rotation (`POST /v1/organizations/{org_id}/credentials/{id}/rotate` and `scripts/rotate_secrets.py`) and `RateLimitMiddleware` (`app/core/rate_limit.py`) | unit + integration tests pass |
| P9-S06 | Write `docs/threat-model.md` (STRIDE + OWASP API Top 10 + OWASP LLM/Agentic Top 10 → controls → test IDs); harden `infra/docker/api.Dockerfile`, `frontend/Dockerfile`, and `.github/workflows/ci.yml` | CI config + security tests pass |
| P9-S07 | Export `openapi.json`, run `gen:api`, add webhook trigger UI on `WorkflowDetailPage` and credential rotation button on `CredentialsPage` | Vitest tests pass |
| P9-S08 | Labs (DNS rebinding / redirect SSRF defense, concurrent budget exhaustion race, webhook replay attack) + progress log | recorded in `docs/lab-notes/phase-09.md` |

## Files
```text
alembic/versions/0007_triggers_budgets.py
app/infrastructure/http_tool/egress.py
app/modules/usage/budget.py
app/modules/triggers/{__init__,models,schemas,repository,service,router}.py
app/core/rate_limit.py
scripts/rotate_secrets.py
frontend/Dockerfile   frontend/nginx.conf
tests/security/{test_ssrf_egress,test_webhook_hmac,test_budget_concurrency,test_rate_limits,test_bola_matrix}.py
docs/threat-model.md   docs/lab-notes/phase-09.md
```

## Security & algorithm contracts

### 1. DNS-Rebinding-Safe Egress Validator (`app/infrastructure/http_tool/egress.py`)
Blocked networks (`BLOCKED_NETWORKS`):
`0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.168.0.0/16`, `198.18.0.0/15`, `224.0.0.0/4`, `240.0.0.0/4`, `::1/128`, `fc00::/7`, `fe80::/10`, `::ffff:0:0/96`.
Validation and connection sequence for URL `u`:
1. Parse with `urllib.parse.urlsplit(u)`. Require `scheme == "https"`, `username is None`, `password is None`, `port in (None, 443, 8443)`, and `hostname` in `allowed_hosts`.
2. Reject IP literals directly when `settings.egress_block_private` is `True` and the IP falls in `BLOCKED_NETWORKS` (or `ip.is_private`, `ip.is_loopback`, `ip.is_link_local`, `ip.is_multicast`, `ip.is_reserved`, `ip.is_unspecified`).
3. Resolve hostname via `await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)`. If empty → raise `EgressBlockedError`.
4. For **every** resolved IP address (including IPv4-mapped IPv6 `ip.ipv4_mapped`), verify it is not in `BLOCKED_NETWORKS` and none of the `is_private`/`is_loopback`/`is_link_local`/`is_reserved` flags are true (when `settings.egress_block_private` is `True`). If **any** resolved IP is blocked → raise `EgressBlockedError("EGRESS_BLOCKED")`.
5. **Pin the first validated IP** for the connection: connect to `https://<pinned_ip>:<port><path>` with `Host: <hostname>` header and `extensions={"sni_hostname": hostname}` in `httpx` so a second DNS lookup cannot rebind to `127.0.0.1` or `169.254.169.254`. Redirects remain strictly disabled (`follow_redirects=False`).

### 2. Two-Phase Budget Reservation & Settlement (`app/modules/usage/budget.py`)
1. **At Run Trigger (`POST /v1/workflows/{id}/runs` and webhook trigger):**
   Inside the `SELECT ... FROM organizations WHERE id = :org_id FOR UPDATE` lock:
   Compute current spend + active reservations:
   ```sql
   SELECT
     COALESCE((SELECT SUM(settled_micro_usd) FROM budget_reservations WHERE org_id = :org_id AND state = 'SETTLED'), 0)
     + COALESCE((SELECT SUM(reserved_micro_usd) FROM budget_reservations WHERE org_id = :org_id AND state = 'RESERVED'), 0)
   ```
   If `current_committed_and_reserved >= org.budget_limit_micro_usd` → raise `402 BUDGET_EXCEEDED`.
2. **Before each LLM step (`reserve_budget`):**
   Compute `max_step_cost = ((step.config.max_tokens + 1000) * settings.llm_price_per_1k_tokens_micro_usd) // 1000 * 2` (covers up to 2 attempts).
   In a transaction: lock `organizations` row `FOR UPDATE`, compute `committed + reserved + max_step_cost`.
   - If it exceeds `org.budget_limit_micro_usd`: fail the step and run with `error_code = 'BUDGET_EXCEEDED'` (`retryable = False`).
   - Otherwise upsert `budget_reservations` (`org_id`, `run_id`, `step_id`, `reserved_micro_usd = max_step_cost`, `state = 'RESERVED'`). Commit.
3. **After the LLM step completes (`settle_budget` / `release_budget`):**
   - On step completion (or final failure after LLM calls): sum actual `estimated_cost_micro_usd` recorded in `usage_records` for `(run_id, step_id)` and update `budget_reservations SET settled_micro_usd = :actual, state = 'SETTLED', settled_at = now() WHERE run_id = :run_id AND step_id = :step_id`.
   - If no LLM call was made before failure/cancel: update `state = 'RELEASED', settled_micro_usd = 0, settled_at = now()`.

### 3. Signed Webhook Trigger (`POST /v1/triggers/webhooks/{trigger_id}`)
1. Load `triggers` by `trigger_id` (`enabled = True`) and its linked `integration_credentials` row. If missing or disabled → `404 NOT_FOUND`.
2. Read headers `X-FlowForge-Timestamp` and `X-FlowForge-Signature`.
   - Parse `timestamp = int(ts_header)`. If `abs(now_epoch - timestamp) > settings.webhook_timestamp_tolerance_seconds` → raise `401 WEBHOOK_REPLAY`.
   - Decrypt the credential secret; compute `expected = "v1=" + hmac.new(secret, f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()`.
   - Verify with `hmac.compare_digest(expected, sig_header)`. If false → raise `401 WEBHOOK_SIGNATURE_INVALID`.
3. **Replay deduplication:**
   Construct `idempotency_key = f"webhook:{trigger_id}:{sig_header}"`.
   Call the run creation service with `trigger_kind="webhook"`, `trigger_id=trigger.id`, `idempotency_key=idempotency_key`, and `inputs=json_body.get("inputs", json_body)`.
   If `(org_id, idempotency_key)` already exists in `workflow_runs` → raise `401 WEBHOOK_REPLAY` (unlike manual `Idempotency-Key` which returns the existing run, a replayed webhook delivery is rejected or deduplicated without creating a second run; wait — to satisfy both webhook retry safety and replay rejection: if `request_fingerprint` matches and the run was created within the 300 s window, return `202` with `Idempotency-Replayed: true` and 0 new runs; if the signature is reused with any difference or after revocation, return `401 WEBHOOK_REPLAY`).

## API contracts
| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `POST /v1/workflows/{id}/triggers` | `{"credential_id": uuid}` | `201` `TriggerOut` (`id`, `workflow_id`, `credential_id`, `enabled`, `webhook_url`) | 404; 403; 422 |
| `POST /v1/triggers/webhooks/{trigger_id}` | Headers `X-FlowForge-Timestamp`, `X-FlowForge-Signature`; JSON body | `202` `RunResponse` | 401 `WEBHOOK_SIGNATURE_INVALID`, `WEBHOOK_REPLAY`; 402 `BUDGET_EXCEEDED`; 404; 422; 429 |
| `POST /v1/organizations/{org_id}/credentials/{id}/rotate` | `{"secret": str(1–4096)}` | `200` `CredentialOut` (`rotated_at` updated, encrypted with active `key_id`) | 404; 403; 422 |

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P9-T01 | test_ssrf_egress | Egress validator rejects `127.0.0.1`, `10.0.0.1`, `172.16.0.5`, `192.168.1.1`, `169.254.169.254` (cloud metadata), `::1`, `::ffff:127.0.0.1`, `fe80::1`, non-HTTPS schemes, and ports other than `443`/`8443` |
| P9-T02 | test_ssrf_egress | **DNS rebinding test:** custom resolver returns public IP on call 1 and `169.254.169.254` on call 2; pinned-IP transport resolves once and connects only to the validated IP (or rejects if any resolved IP in the set is private) |
| P9-T03 | test_ssrf_egress | Upstream returning `302 Location: http://169.254.169.254/latest/meta-data/` is **not** followed (`follow_redirects=False`) |
| P9-T04 | test_webhook_hmac | Valid HMAC + fresh timestamp → `202` and creates 1 run; wrong signature → `401 WEBHOOK_SIGNATURE_INVALID`; timestamp 600 s old → `401 WEBHOOK_REPLAY` |
| P9-T05 | test_webhook_hmac | Duplicate delivery of identical signed webhook within window returns `202` (`Idempotency-Replayed: true`) and creates **no** second run |
| P9-T06 | test_budget_concurrency | **Budget race:** org budget is `10,000` micro-USD, each AI step reserves `3,000`; firing 10 concurrent runs allows at most 3 to reserve (`9,000 <= 10,000`) and fails the remaining 7 with `BUDGET_EXCEEDED`; total settled + reserved never exceeds `10,000` |
| P9-T07 | test_rate_limits | 11th login attempt within 1 minute from same IP+email returns `429 RATE_LIMITED` with `Retry-After` header |
| P9-T08 | test_bola_matrix | Comprehensive BOLA matrix test: user in Org B attempts every read/write endpoint (`/workflows/{id}`, `/versions`, `/runs/{id}`, `/cancel`, `/retry`, `/approvals/{id}/decisions`, `/credentials/{id}/rotate`, `/usage`, `/audit-events`) on Org A's resource IDs → every single call returns `404` |

## Frontend
- Webhook trigger card on `WorkflowDetailPage` (create trigger, copy webhook URL, example `curl` snippet showing `X-FlowForge-Timestamp` and `X-FlowForge-Signature`).
- "Rotate secret" modal on `CredentialsPage`.
- `frontend/nginx.conf` sets `Content-Security-Policy: default-src 'self'; connect-src 'self' http://localhost:8000; frame-ancestors 'none'; object-src 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
- Frontend tests: `P9-F01` creates webhook trigger and displays URL; `P9-F02` rotates credential secret and updates `rotated_at`.

## Labs (`docs/lab-notes/phase-09.md`)
1. **SSRF & DNS Rebinding lab:** attempt 6 bypass vectors (decimal IP, IPv6-mapped IPv4 `::ffff:169.254.169.254`, HTTP 302 redirect to metadata IP, dual A-record with 1 public + 1 private IP, DNS rebinding between check and use, non-standard port `6379`) and verify all 6 are blocked.
2. **Concurrent budget exhaustion lab:** run 20 concurrent AI workflow executions against a capped org budget and prove `SUM(settled_micro_usd) <= budget_limit_micro_usd`.

## Verification commands
```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P9-T01…T08 and P9-F01…F02 pass.
- [ ] `docs/threat-model.md` and Labs 1–2 completed; Phase 9 PDF built.

## Agent brief
**Do:** use `hmac.compare_digest` for all signature checks and hold the `organizations` `FOR UPDATE` lock during budget reservation. **Don't:** follow redirects in `httpx` or store plaintext webhook secrets. **Stop and report** if any endpoint in the app is missing from `test_bola_matrix.py`.
