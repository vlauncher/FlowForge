# Phase 2 Spec: Data Layer, Identity and Tenancy

Learning material: `flowforge.md` → Phase 2. Contracts: `spec/00-global.md` (§1 conventions, §2 permissions, §3 tables `users`, `refresh_tokens`, `organizations`, `memberships`, `workflows`, `workflow_versions`; §7 errors; §10 security). **Prerequisite:** Phase 1 done-when is green.

## Scope
PostgreSQL + async SQLAlchemy + Alembic, signup/login/refresh/logout, organizations and memberships, workflow shells (create/list/get; **versions are Phase 3**), tenant-isolation tests, frontend auth and org/workflow screens. Creates tables `users`, `refresh_tokens`, `organizations`, `memberships`, `workflows`, `workflow_versions` (the latter only as a table + immutability trigger).

## Config additions (`Settings`)
`database_url`, `db_pool_size=10`, `db_max_overflow=10`, `jwt_secret` (required, ≥ 32 chars, validator), `jwt_issuer="flowforge"`, `jwt_audience="flowforge-api"`, `access_token_ttl_seconds=900`, `refresh_token_ttl_seconds=604800`, `password_min_length=12`. `.env.example` gets placeholders (`JWT_SECRET=change-me-to-a-random-string-of-32-chars-or-more`).

## Steps
| ID | Step | Done when |
|---|---|---|
| P2-S01 | Add `postgres` service to `compose.yaml` (pick current stable image tag via `docker pull`, record in `docs/dependency-notes.md`; volume `pgdata`; healthcheck `pg_isready -U flowforge -d flowforge`; port `127.0.0.1:5432:5432`); add `migrate` one-shot service | `docker compose up -d postgres` healthy |
| P2-S02 | `app/infrastructure/db/{base.py,session.py}`: `Base` with naming convention (`ix`, `uq`, `ck`, `fk`, `pk` per Alembic docs), `create_engine(settings)`, `async_sessionmaker(expire_on_commit=False)`, `get_session` dependency | import works |
| P2-S03 | Alembic init (async template), `alembic.ini` (no URL; read from settings in `env.py`), revision `0001_identity_orgs` | `alembic upgrade head` on empty DB succeeds |
| P2-S04 | Models + revision `0002_workflows` (incl. trigger SQL below) | `alembic upgrade head` then `downgrade base` then `upgrade head` succeeds |
| P2-S05 | `app/domain/permissions.py` (matrix from spec §2) | unit tests pass |
| P2-S06 | Identity module: hashing, JWT, refresh rotation, endpoints | tests pass |
| P2-S07 | Organization + membership module | tests pass |
| P2-S08 | Workflow module (create/list/get) with cursor pagination | tests pass |
| P2-S09 | Register `db` readiness check; update OpenAPI export; `gen:api` | `openapi.json` updated |
| P2-S10 | Frontend screens | `npm test` passes |
| P2-S11 | Labs + ADR-002 + docs | evidence in `docs/lab-notes/phase-02.md` |

## Files
```text
alembic.ini  alembic/env.py  alembic/versions/{0001_identity_orgs,0002_workflows}.py
app/infrastructure/db/{__init__,base,session}.py
app/domain/permissions.py
app/core/security.py                # hash_password, verify_password, create_access_token, decode_access_token, new_refresh_token, hash_token
app/core/pagination.py              # encode_cursor, decode_cursor, Page
app/api/deps.py                     # get_current_user, get_membership, require_permission
app/modules/identity/{models,schemas,repository,service,router}.py
app/modules/organizations/{models,schemas,repository,service,router}.py
app/modules/workflows/{models,schemas,repository,service,router}.py
tests/integration/{conftest,test_migrations,test_auth,test_orgs,test_members,test_workflows,test_tenancy,test_constraints,test_pagination}.py
tests/unit/{test_permissions,test_security,test_pagination_codec}.py
frontend/src/{auth,features/orgs,features/workflows,components}/…
docs/lab-notes/phase-02.md  docs/adr/ADR-002-tenant-isolation.md
```

## Database specifics (beyond spec §3)
- Types: `uuid`, `text`, `boolean`, `timestamptz`, `bigint`, `int`, `jsonb`. Use SQLAlchemy 2 typed `Mapped[...]`/`mapped_column`. Python `datetime` columns are timezone-aware UTC.
- `users.email` is stored lowercase; unique index `ux_users_email`.
- Immutability trigger (in migration `0002`, raw SQL, with matching `downgrade`):
```sql
CREATE FUNCTION forbid_published_version_change() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'published' THEN
    RAISE EXCEPTION 'published workflow versions are immutable' USING ERRCODE = 'P0001';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_workflow_versions_immutable BEFORE UPDATE OR DELETE ON workflow_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_published_version_change();
```
- `workflows.current_version_id` FK to `workflow_versions(id)` is `DEFERRABLE INITIALLY DEFERRED` (circular reference).
- Pool: `pool_size`, `max_overflow` from settings, `pool_pre_ping=True`.

## Session and transaction rules
1. `get_session` yields one `AsyncSession` per request; on exception it rolls back; the context manager closes it.
2. Services receive the session; a use case ends with `await session.commit()`. Repositories never commit.
3. Never share a session between concurrent tasks. Never call out to the network while a transaction holds row locks.
4. No lazy loading: queries use explicit joins or `selectinload`; `lazy="raise"` on every relationship.

## Tenant access rules
- `get_membership(org_id, user)` → returns the membership or raises `NotFound()` (never 403 for non-members).
- ID-based routes load the object **joined with the caller's membership** in one query: `SELECT w.* FROM workflows w JOIN memberships m ON m.org_id = w.org_id AND m.user_id = :uid WHERE w.id = :id`. No row → `NotFound()`. Then `require_permission(role, action)` → `Forbidden()` if the role lacks the action.
- Every repository method that reads tenant data takes `org_id` as a required parameter (keyword-only). A test greps the repository code for queries on tenant tables lacking an `org_id` condition (P2-T30).

## API contracts
Auth endpoints return `TokenResponse`:
```json
{"access_token": "<jwt>", "token_type": "bearer", "expires_in": 900,
 "user": {"id": "uuid", "email": "a@b.co", "display_name": "Ada", "created_at": "2026-10-25T10:00:00Z"}}
```
Refresh token is **only** in the cookie `ff_refresh` (`HttpOnly; SameSite=Strict; Path=/v1/auth; Max-Age=604800; Secure` when `app_env != "dev"`). `refresh` and `logout` require header `X-FlowForge-CSRF: 1`, otherwise `403 FORBIDDEN`.

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `POST /v1/auth/signup` | `{"email": str, "password": str(12–128), "display_name": str(1–80)}` | 201 `TokenResponse` + cookie | 409 `EMAIL_TAKEN`; 422 |
| `POST /v1/auth/login` | `{"email","password"}` | 200 `TokenResponse` + cookie | 401 `INVALID_CREDENTIALS`; 422 |
| `POST /v1/auth/refresh` | cookie + CSRF header | 200 `TokenResponse` + rotated cookie | 401 `UNAUTHENTICATED` (missing/invalid/expired/revoked); 403 no CSRF header |
| `POST /v1/auth/logout` | cookie + CSRF header | 204, cookie cleared, token revoked | — (idempotent: no cookie is still 204) |
| `GET /v1/me` | — | 200 `{"id","email","display_name","created_at","memberships":[{"org_id","org_name","role"}]}` | 401 |
| `POST /v1/organizations` | `{"name": str(1–80), "slug"?: str}` (slug derived from name if omitted: lowercase, non-alphanumerics → `-`, trimmed, suffix `-2`, `-3`… on conflict up to 5 tries) | 201 `Org` | 409 `CONFLICT` (explicit slug taken); 422 |
| `GET /v1/organizations` | `limit`, `cursor` | 200 page of `Org` the caller belongs to, with `my_role` | 400 bad cursor |
| `GET /v1/organizations/{org_id}` | — | 200 `Org` | 404 |
| `GET /v1/organizations/{org_id}/members` | `limit`, `cursor` | 200 page of `{"user_id","email","display_name","role","created_at"}` | 404 |
| `POST /v1/organizations/{org_id}/members` | `{"email","role"}` | 201 member | 404 (org, or no user with that email); 403; 409 `CONFLICT` already a member |
| `PATCH /v1/organizations/{org_id}/members/{user_id}` | `{"role"}` | 200 member | 404; 403 (admin touching an owner or granting `owner`); 409 `LAST_OWNER` |
| `POST /v1/organizations/{org_id}/workflows` | `{"display_name": str(1–120), "description"?: str(≤1000)}` | 201 `Workflow` | 404; 403; 422 |
| `GET /v1/organizations/{org_id}/workflows` | `limit`, `cursor`, `include_archived` (bool, default false) | 200 page of `Workflow` | 404; 400 |
| `GET /v1/workflows/{id}` | — | 200 `Workflow` | 404 |

`Org`: `{"id","name","slug","plan","budget_limit_micro_usd","max_concurrent_runs","created_at","my_role"}`.
`Workflow`: `{"id","org_id","display_name","description","current_version_id","archived_at","created_by","created_at","updated_at"}`.
Note: "no user with that email → 404" reveals whether an email is registered; accepted for MVP and recorded in `docs/risks.md`.

### Cursor encoding
`base64url(json.dumps({"c": "<created_at iso>", "i": "<uuid>"}))`; keyset predicate `(created_at, id) < (:c, :i)` with `ORDER BY created_at DESC, id DESC`; fetch `limit+1` to compute `next_cursor`. A cursor that fails to decode or has wrong keys → `400 BAD_REQUEST`. Max `limit` 100, `limit < 1` → 422.

### Security helpers
- `hash_password`: `argon2.PasswordHasher()` defaults; `verify_password` catches `VerifyMismatchError`, returns bool; also rehash-on-login when `check_needs_rehash`.
- Login for an unknown email still calls `verify_password` against a fixed dummy hash to equalise timing.
- `create_access_token(user_id)`: claims `sub`, `iat`, `exp`, `iss`, `aud`, `jti=uuid`; HS256. `decode_access_token` requires all of `exp`, `iat`, `sub`, `iss`, `aud`; any `PyJWTError` → `Unauthenticated()`.
- Refresh token: `secrets.token_urlsafe(32)`; store `sha256(token)` hex. Rotation on `/refresh`: in one transaction mark old `revoked_at=now()`, insert the new row, set `replaced_by`. If a **revoked** token is presented, revoke every token of that user chained after it (follow `replaced_by`) and return 401.
- Never log tokens, passwords or hashes (redaction processor covers keys).

## Algorithms
**Create organization** (single transaction): insert org; insert membership `(org, user, 'owner')`; commit. **Change role**: lock the org's owner rows `SELECT … FOR UPDATE` on memberships of that org with role `owner`; if the change removes the last owner → `LastOwner` (409); update; commit. **Add member**: lookup user by email; insert; unique violation → `Conflict`.

## Test cases
Integration tests use a real PostgreSQL: session fixture starts `testcontainers` `PostgresContainer` (same image tag as compose), runs `alembic upgrade head` once, and a function-scoped fixture `TRUNCATE`s all tables (`RESTART IDENTITY CASCADE`) before each test. Tests build the app with the container URL and call it through `httpx.AsyncClient`.

| ID | Test |
|---|---|
| P2-T01 | `alembic upgrade head` on an empty DB succeeds; `downgrade base`; `upgrade head` again succeeds |
| P2-T02 | Signup returns 201 with a token and sets the `ff_refresh` cookie (HttpOnly, SameSite=Strict, Path=/v1/auth) |
| P2-T03 | Signup with an existing email (any case) → 409 `EMAIL_TAKEN`; password of 11 chars → 422 |
| P2-T04 | Login success; wrong password and unknown email both → 401 `INVALID_CREDENTIALS` with identical bodies |
| P2-T05 | `GET /v1/me` without token → 401 `UNAUTHENTICATED`; with expired token → 401; with token of wrong audience/issuer/signature → 401 |
| P2-T06 | Refresh rotates: old cookie reused afterwards → 401 and the new token chain is revoked |
| P2-T07 | Refresh/logout without `X-FlowForge-CSRF` → 403; logout revokes token; second logout still 204 |
| P2-T08 | Create org: caller becomes `owner`; slug auto-generated; explicit duplicate slug → 409 `CONFLICT` |
| P2-T09 | `GET /v1/organizations` returns only the caller's orgs |
| P2-T10 | User B requesting org A (`GET /v1/organizations/{A}`) → 404 (not 403) |
| P2-T11 | Add member (admin) works; duplicate → 409; unknown email → 404; viewer adding → 403 |
| P2-T12 | Admin cannot grant `owner` or change an owner's role → 403 |
| P2-T13 | Demoting the only owner → 409 `LAST_OWNER`; concurrent demotion of two owners (two simultaneous requests) leaves at least one owner |
| P2-T14 | Create workflow as owner/admin → 201; as operator/reviewer/viewer → 403 |
| P2-T15 | Workflow in org A: `GET /v1/workflows/{id}` as org B user → 404; as org A viewer → 200 |
| P2-T16 | List workflows excludes archived by default; `include_archived=true` includes them |
| P2-T17 | Pagination: create 30 workflows, `limit=10` → 3 pages, no duplicates or gaps, descending order, stable when a new workflow is inserted between page fetches |
| P2-T18 | Bad cursor → 400; `limit=0` and `limit=101` → 422 |
| P2-T19 | DB: duplicate `(org_id,user_id)` membership rejected by the database (IntegrityError) |
| P2-T20 | DB: workflow_versions `(workflow_id, version)` duplicate rejected; published row without checksum rejected by CHECK |
| P2-T21 | DB: UPDATE and DELETE of a `published` workflow_versions row raise (trigger), a `draft` row can be updated |
| P2-T22 | DB: a second `draft` for one workflow rejected by the partial unique index |
| P2-T23 | Failed request rolls back: force an error after an insert inside a service and assert no row remains |
| P2-T24 | `/ready` returns 200 with `checks.db="ok"`; with the DB stopped/invalid URL → 503 |
| P2-T25 | Unit: permission matrix — every role/action pair equals the table in spec §2 (parametrised from a copy of the table in the test) |
| P2-T26 | Unit: access token round-trip; tampered token, `alg=none` token, wrong key all rejected |
| P2-T27 | Unit: cursor codec round trip and malformed inputs |
| P2-T28 | Request body with unknown field → 422 (`extra="forbid"`) |
| P2-T29 | Sessions: two concurrent requests use distinct sessions (assert different session ids through a test dependency override) |
| P2-T30 | Static check: every repository function touching `workflows`, `workflow_versions`, `memberships` has an `org_id` parameter (script `scripts/check_tenant_params.py` run as a test) |

## Frontend
Routes: `/login`, `/signup`, `/orgs` (list + create), `/orgs/:orgId/workflows` (list + create), `*` → not found page. Protected routes redirect to `/login?next=…`.

| Piece | Spec |
|---|---|
| Auth state | `AuthProvider`: access token in memory only. On start call `POST /v1/auth/refresh` (with `X-FlowForge-CSRF: 1`, `credentials: "include"`) to restore a session; while pending show a loading screen. `apiFetch` adds `Authorization`; on a 401 from any call except auth endpoints it calls refresh once, retries once, else clears state and goes to `/login` |
| Signup form | `email` (type=email, required), `display_name` (1–80, required), `password` (≥ 12 chars, show/hide toggle, requirement hint). Submit disabled while pending. Server `errors[].field` mapped under each input via `aria-describedby`; `EMAIL_TAKEN` shown on the email field |
| Login form | `email`, `password`; on `INVALID_CREDENTIALS` show a form-level message "Email or password is incorrect" |
| Layout | Header with org switcher (`<select>` of the user's orgs, selection navigates to `/orgs/:id/workflows` and is stored in `localStorage` key `ff.lastOrg`), user name, "Log out" button |
| Orgs page | list (name, slug, role), "Create organization" form (`name`, optional `slug`) |
| Workflows page | table: name, description, created (local time), archived badge; empty state "No workflows yet"; "New workflow" form for roles owner/admin only (hidden otherwise, still enforced by the API); "Load more" when `next_cursor`; loading skeleton; error state with `code` and `request_id` |
Tests: P2-F01 ApiError mapping & refresh-once-retry logic (mock fetch); P2-F02 signup shows field errors; P2-F03 login failure message; P2-F04 protected route redirects; P2-F05 workflow list empty/error/loaded states; P2-F06 "New workflow" hidden for viewer role; P2-F07 org switch navigates. Playwright smoke test (`frontend/e2e/auth.spec.ts`, runs against `docker compose` stack): sign up → create org → create workflow → appears in list.

## Compose and Docker changes
`migrate` service: same image as `api`, command `alembic upgrade head`, `depends_on: postgres (service_healthy)`, `restart: "no"`. `api` depends on `migrate (service_completed_successfully)`. Dockerfile also copies `alembic/` and `alembic.ini`.

## Labs (record in `docs/lab-notes/phase-02.md`)
1. Share one `AsyncSession` between two `asyncio.gather` tasks; capture the error; show the per-task fix.
2. Lost update: two concurrent role changes at Read Committed without locking; then with `SELECT … FOR UPDATE`. Show both outcomes.
3. Remove the `org_id` join from one repository query on a scratch branch; show P2-T10/T15/T30 catch it; revert.
4. `EXPLAIN (ANALYZE, BUFFERS)` of the workflow list query with 10,000 rows, with and without the `(org_id, created_at DESC, id DESC)` index; record before/after numbers (hardware noted).

## Verification commands
```bash
docker compose up -d postgres
alembic upgrade head && alembic downgrade base && alembic upgrade head
ruff check . && ruff format --check . && mypy app && pytest -q          # 16 old + new tests pass
python scripts/export_openapi.py && git diff --exit-code openapi.json   # after committing the intended update
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P2-T01…T30, P2-F01…F07 and the Playwright smoke test pass.
- [ ] 4 labs recorded; ADR-002 written; `docs/risks.md` updated (email enumeration, shared-schema tenancy).
- [ ] `flowforge.md` Phase 2 progress log filled; phase PDF built.

## Agent brief
**Do:** only listed files. **Don't:** implement versions/validation (Phase 3); add roles or permissions beyond spec §2; store the access token in `localStorage`/`sessionStorage`; return secrets or hashes in any response. **Stop and report** if: an installed library's API differs from this spec (name the exact version and the difference), a migration can't downgrade cleanly, or Docker isn't available for integration tests.
