# Phase 1 Spec: Foundations and Discovery

Learning material: `flowforge.md` → Phase 1. Contracts: `spec/00-global.md` (conventions §1, errors §7, config §9, deps §12). **Prerequisites:** none (empty repo with `docs/`, `scripts/`, `flowforge.md`, `spec/`).

## Scope
Backend skeleton (factory, config, errors, request ID, CORS, body limit, JSON logging, redaction, health/ready), tooling, CI, Dockerfile + compose (api only), OpenAPI export, frontend shell with health page, discovery docs. **No database, no auth, no business endpoints.**

## Steps (execute in order; commit after each)
| ID | Step | Done when |
|---|---|---|
| P1-S01 | Create `.python-version` (`3.14`), `.gitignore` additions (`.env`, `.venv/`, `node_modules/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`), `.env.example` | files exist |
| P1-S02 | Create venv `.venv`; write `requirements.in` and `requirements-dev.in` from spec §12 | files exist |
| P1-S03 | `pip-compile` both files to `requirements.txt` / `requirements-dev.txt` (with hashes: `--generate-hashes`). If a version fails on Python 3.14, lower **only** that package and note it in `docs/dependency-notes.md` | `pip install -r requirements-dev.txt` succeeds |
| P1-S04 | `pyproject.toml` (ruff, mypy strict, pytest) | `ruff check .` and `mypy app` run |
| P1-S05 | Core modules (below) | unit tests pass |
| P1-S06 | API routes: health, ready, `/v1` router (empty) | tests pass |
| P1-S07 | `scripts/export_openapi.py`, commit `openapi.json` | script is deterministic (run twice, no diff) |
| P1-S08 | Dockerfile, `compose.yaml` (api only) | `docker compose up --build` serves `/health` |
| P1-S09 | Frontend shell | `npm run lint`, `tsc`, `vitest`, `build` pass |
| P1-S10 | CI workflow | file valid YAML (cannot run locally unless `act` exists) |
| P1-S11 | Discovery docs + state diagram doc | files meet the content lists below |
| P1-S12 | Pre-commit config | `pre-commit run --all-files` passes |
| P1-S13 | Labs (event-loop starvation) + write ADR-001 check + progress log | evidence recorded in `docs/lab-notes/phase-01.md` |

## Files to create
```text
.python-version  .env.example  pyproject.toml  requirements*.in/.txt  .pre-commit-config.yaml
compose.yaml  infra/docker/api.Dockerfile  openapi.json
app/__init__.py
app/main.py
app/core/{__init__,config,errors,ids,logging,redaction,request_context,middleware,readiness}.py
app/api/{__init__,health}.py
app/api/v1/__init__.py
scripts/export_openapi.py
tests/conftest.py   tests/unit/{test_config,test_errors,test_request_id,test_cors,test_body_limit,test_health,test_redaction,test_ids,test_openapi}.py
frontend/...  .github/workflows/ci.yml
docs/00-problem.md  docs/constraints.md  docs/risks.md  docs/state-machine.md  docs/lab-notes/phase-01.md
```

## Module contracts

### `app/core/config.py`
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["dev", "test", "prod"] = "dev"          # APP_ENV
    log_level: str = "INFO"                                  # LOG_LEVEL
    api_cors_origins: list[str] = ["http://localhost:5173"]  # API_CORS_ORIGINS (comma separated string accepted)
    max_request_bytes: int = 1_048_576                       # MAX_REQUEST_BYTES (>0)
@lru_cache def get_settings() -> Settings
```
Validators: `api_cors_origins` must not contain `*` and every entry must start with `http://` or `https://` (raise `ValueError`). Comma-separated parsing via a `field_validator(mode="before")`. Later phases **add** fields; they don't change these.

### `app/core/ids.py`
`def new_id() -> uuid.UUID: return uuid.uuid7()`. (stdlib)

### `app/core/request_context.py`
`request_id_var: ContextVar[str | None]`; `get_request_id() -> str | None`.

### `app/core/middleware.py` (pure ASGI classes, not `BaseHTTPMiddleware`)
- `RequestIdMiddleware`: reads `X-Request-ID`; if it matches `^[A-Za-z0-9._-]{8,64}$` use it, else `str(new_id())`. Sets the contextvar, stores it in `scope["state"]["request_id"]`, adds `X-Request-ID` to the response start message. Resets the contextvar after the request.
- `BodySizeLimitMiddleware(max_bytes)`: if `Content-Length` > max → respond `413` Problem Details `PAYLOAD_TOO_LARGE` without reading the body. Otherwise wrap `receive` to count bytes; if the total exceeds max, respond 413 (only if the response hasn't started).
Order (outermost first): `RequestIdMiddleware`, `CORSMiddleware`, `BodySizeLimitMiddleware`.

### `app/core/errors.py`
```python
class AppError(Exception):
    def __init__(self, code: str, status: int, title: str, detail: str | None = None,
                 errors: list[dict] | None = None, headers: dict[str, str] | None = None): ...
def problem_response(request, *, code, status, title, detail, errors=None, headers=None) -> JSONResponse
def install_error_handlers(app: FastAPI) -> None
```
Response: `Content-Type: application/problem+json`; body per spec §1 (`type`, `title`, `status`, `detail`, `instance` = request path, `code`, `request_id`, optional `errors`). Subclasses defined now for every code in spec §7 as thin factory functions or classes (`NotFound()`, `Forbidden()`, `Unauthenticated()`, `Conflict(detail)`, `InvalidStateTransition(detail)`, …) so later phases only import them.
Handlers:
| Exception | Result |
|---|---|
| `AppError` | its own code/status |
| `RequestValidationError` | if any error has `type == "json_invalid"` → 400 `BAD_REQUEST`; else 422 `VALIDATION_ERROR` with `errors=[{"field": ".".join(str(p) for p in loc if p not in ("body","query","path")), "message": msg}]` (cap 50 entries) |
| `StarletteHTTPException` | 404→`NOT_FOUND`, 405→`METHOD_NOT_ALLOWED`, 401→`UNAUTHENTICATED`, 403→`FORBIDDEN`, other 4xx→`BAD_REQUEST`; detail is the generic title (never echo internals) |
| `Exception` | log with traceback (structured, with request id); respond 500 `INTERNAL_ERROR`, `detail="An unexpected error occurred."` |
Note: handlers for unhandled `Exception` must be registered so the response still gets `X-Request-ID` (the `RequestIdMiddleware` is outermost, so it adds the header).

### `app/core/logging.py`
`configure_logging(level: str)`: structlog → JSON lines on stdout with keys `timestamp` (ISO UTC), `level`, `event`, `logger`, `request_id` (from contextvar), plus bound fields. Processor chain includes `redact_processor` from `redaction.py`.

### `app/core/redaction.py`
`SENSITIVE_KEY = re.compile(r"(?i)(password|secret|token|authorization|api[_-]?key|cookie)")`; `redact(value, *, max_depth=8) -> Any` returns a copy where dict values whose key matches become `"***"`, recursing into dicts and lists (depth limited, beyond → `"…"`). Never mutates the input.

### `app/core/readiness.py`
```python
ReadinessCheck = Callable[[], Awaitable[None]]   # raises on failure
def register_check(name: str, fn: ReadinessCheck) -> None
async def run_checks() -> dict[str, str]          # {"name": "ok"|"fail"}; each check has a 2 s timeout
```
Later phases register `db` (P2) and `broker` (P4).

### `app/api/health.py`
- `GET /health` → `200 {"status":"ok"}` (no dependencies, never touches DB).
- `GET /ready` → all checks ok → `200 {"status":"ready","checks":{...}}`; any fail → `503` Problem Details `SERVICE_UNAVAILABLE` with extra member `checks`.
Both excluded from auth; tagged `ops` in OpenAPI.

### `app/main.py`
`def create_app(settings: Settings | None = None) -> FastAPI` — builds the app with `title="FlowForge API"`, `version="0.1.0"`, `docs_url="/docs"` (disabled when `app_env=="prod"`), includes routers, middleware, handlers, calls `configure_logging`. `lifespan` is present but empty (later phases add engine/broker setup). No module-level `app` global; run with `uvicorn app.main:create_app --factory`.

## Test cases (all in `tests/unit/`, use `httpx.AsyncClient(transport=ASGITransport(app))`)
| ID | File | Given / When / Then |
|---|---|---|
| P1-T01 | test_health | GET /health → 200 `{"status":"ok"}` with `X-Request-ID` header |
| P1-T02 | test_health | No checks registered, GET /ready → 200 `{"status":"ready","checks":{}}` |
| P1-T03 | test_health | A registered failing check → GET /ready → 503, `code=SERVICE_UNAVAILABLE`, `checks.<name>="fail"` |
| P1-T04 | test_request_id | No header → response has a UUID request id; same id appears in an error body |
| P1-T05 | test_request_id | Valid client id `abc-12345` echoed; invalid id (`"x"`, 100 chars, spaces) replaced |
| P1-T06 | test_errors | Unknown route → 404 `NOT_FOUND`, content-type `application/problem+json`, no `traceback`/`File "` in body |
| P1-T07 | test_errors | Wrong method on /health → 405 `METHOD_NOT_ALLOWED` |
| P1-T08 | test_errors | A test route with a Pydantic body: invalid → 422 `VALIDATION_ERROR` with `errors[0].field` set; malformed JSON → 400 `BAD_REQUEST` |
| P1-T09 | test_errors | A test route raising `RuntimeError("secret-xyz")` → 500 `INTERNAL_ERROR`, body does not contain `secret-xyz`, request id header present |
| P1-T10 | test_cors | Origin `http://localhost:5173` preflight → allowed with credentials header; origin `http://evil.example` → no `access-control-allow-origin` |
| P1-T11 | test_config | `API_CORS_ORIGINS="*"` raises; comma list parsed; `MAX_REQUEST_BYTES=0` raises |
| P1-T12 | test_body_limit | Content-Length above limit → 413 `PAYLOAD_TOO_LARGE`; body under limit passes |
| P1-T13 | test_redaction | Nested dict/list with `password`, `Authorization`, `api_key` keys → `"***"`; input unchanged; deep nesting bounded |
| P1-T14 | test_ids | `new_id()` returns UUID version 7; 1000 ids are unique and sortable by creation |
| P1-T15 | test_openapi | `app.openapi()` contains `/health` and `/ready`; equals the committed `openapi.json` |
| P1-T16 | test_errors | Overriding `get_settings` via `app.dependency_overrides` in one test doesn't leak into the next (two sequential tests assert different values) |

Test config: `pytest.ini_options`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`. `conftest.py` provides `settings` fixture (`APP_ENV=test`) and `client` fixture (builds a fresh app per test).

## Frontend (`frontend/`)
Scaffold manually (do not run interactive generators): `package.json` (scripts: `dev`, `build`, `lint`, `typecheck` = `tsc --noEmit`, `test` = `vitest run`, `gen:api` = `openapi-typescript ../openapi.json -o src/api/schema.d.ts`), `vite.config.ts` (dev port 5173, strict), `tsconfig.json` (strict), `eslint.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/api/client.ts`, `src/api/errors.ts`, `src/features/health/HealthPage.tsx`, `src/styles.css`, `.env.example` (`VITE_API_BASE_URL=http://localhost:8000`).

| Item | Spec |
|---|---|
| `ApiError` | `class ApiError extends Error { status: number; code: string; detail?: string; requestId?: string; errors?: {field:string; message:string}[] }` |
| `apiFetch<T>(path, init?)` | Prefixes `VITE_API_BASE_URL`; sets `Accept: application/json`; if the response is not ok and content-type contains `problem+json`, parse and throw `ApiError`; otherwise throw `ApiError` with `code="NETWORK_OR_UNKNOWN"`; 204 returns `undefined` |
| Route `/` | `HealthPage`: calls `GET /health` and `GET /ready` through React Query (refetch 10 s). States: **loading** ("Checking API…", `role="status"`), **ok** (badge "API healthy", ready checks as a list), **error** (message, `code`, `request_id`, "Retry" button). Keyboard operable, visible focus, colour is not the only indicator |
Frontend tests (Vitest + Testing Library, add `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` to devDependencies): P1-F01 `ApiError` parsed from a problem+json response; P1-F02 `HealthPage` shows loading then ok (mock fetch); P1-F03 shows error with code and request id on 503; P1-F04 network failure shows the generic error.

## CI (`.github/workflows/ci.yml`)
Triggers: `push`, `pull_request`. Permissions: `contents: read`. Jobs: `backend` (python 3.14, `pip install -r requirements-dev.txt`, `ruff check .`, `ruff format --check .`, `mypy app`, `pytest`, `python scripts/export_openapi.py && git diff --exit-code openapi.json`), `frontend` (node 24, `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, working-directory `frontend`). Pin third-party actions by major version tag; note in the ADR backlog that digest pinning is a Phase 9 task.

## Docker
`infra/docker/api.Dockerfile`: `FROM python:3.14-slim`; create user `app` (uid 10001); `WORKDIR /srv`; copy `requirements.txt` and `pip install --no-cache-dir --require-hashes -r requirements.txt`; copy `app/`; `USER app`; `EXPOSE 8000`; `HEALTHCHECK` using Python `urllib` against `/ready`; `CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000"]`. `compose.yaml`: service `api` (build, port `127.0.0.1:8000:8000`, `env_file: .env`, healthcheck). Image tag for Python is `3.14-slim`: confirm it exists with `docker pull`; if not, record the nearest tag.

## Discovery docs: required content
- `docs/00-problem.md`: problem statement, personas (5 from the roadmap), 3 user stories per persona, what the software intentionally won't do (roadmap out-of-scope list).
- `docs/constraints.md`: stack constraints, free-model limits (§9), solo/part-time capacity, provisional non-functional targets (marked as hypotheses).
- `docs/risks.md`: ≥ 10 risks with likelihood, impact, mitigation, owner phase.
- `docs/state-machine.md`: Mermaid `stateDiagram-v2` for run, approval and step-attempt states (from spec §4) plus the transition table.
- `docs/lab-notes/phase-01.md`: event-loop starvation lab (code used, measured `/health` latency with and without the blocking call, conclusion).

## Verification commands (run, don't assume)
```bash
source .venv/bin/activate
ruff check . && ruff format --check . && mypy app     # exit 0
pytest -q                                              # 16 backend tests pass
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build
docker compose up --build -d && curl -s localhost:8000/health   # {"status":"ok"}
curl -si localhost:8000/nope | head -20                          # 404 problem+json with X-Request-ID
docker compose down
```

## Done when (all)
- [ ] P1-T01…T16 and P1-F01…F04 pass; all commands above exit 0.
- [ ] Lab note exists with measured numbers. [ ] Discovery docs meet the content lists.
- [ ] Phase 1 section of `flowforge.md` progress log filled; `scripts/build_pdf.py --phase 1` run.

## Agent brief
**Do:** only the files listed. **Don't:** add DB, auth or business endpoints; add dependencies not in spec §12 (ask first); disable lints or tests; commit `.env`. **Stop and report** if: a pinned version doesn't install, the Python 3.14 image tag is missing, or any test can't be made to pass without changing this spec. **Report:** commands run with real outputs, discrepancies found in this spec.
