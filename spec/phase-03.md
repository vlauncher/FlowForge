# Phase 3 Spec: Workflow Definition and Graph Validation

Learning material: `flowforge.md` → Phase 3. Contracts: `spec/00-global.md` (§3 `workflow_versions`, §5 workflow definition format, §7 errors, §8 API surface). **Prerequisite:** Phase 2 done-when is green.

## Scope
Pure domain workflow definition schema, canonical JSON + SHA-256 checksum, deterministic DAG validator (reachability, cycle detection, step references, template variable ancestry, step config schemas, irreversible-tool approval check), draft creation/editing, validation endpoint, immutable publishing, property-based tests (Hypothesis), and frontend version editor. **No migrations needed** (`workflow_versions` and its immutability trigger were created in `0002_workflows`).

## Steps
| ID | Step | Done when |
|---|---|---|
| P3-S01 | Add `jsonschema` to `requirements.in`, re-run `pip-compile` for `requirements.txt` and `requirements-dev.txt` | `pip install -r requirements-dev.txt` succeeds |
| P3-S02 | `app/domain/workflow_definition.py`: Pydantic models for all 6 step types (`set_data`, `condition`, `http_request`, `llm_classify`, `llm_transform`, `approval`), template parser (`{{ ... }}`), canonical JSON serializer and SHA-256 checksum | unit tests pass |
| P3-S03 | `app/domain/graph_validator.py`: pure validator returning all errors with stable codes (`GRAPH_CYCLE`, `GRAPH_UNREACHABLE_STEP`, `GRAPH_MISSING_STEP`, `UNKNOWN_REFERENCE`, `TYPE_MISMATCH`, `INVALID_STEP_CONFIG`, `FORBIDDEN_TOOL_PERMISSION`, `APPROVAL_REQUIRED_FOR_IRREVERSIBLE`) | unit + Hypothesis tests pass |
| P3-S04 | Extend `app/modules/workflows/{schemas,repository,service,router}.py` with version draft creation, update, list, get, validate, and publish | integration tests pass |
| P3-S05 | Update `openapi.json` and frontend `gen:api` | `git diff --exit-code openapi.json` after commit |
| P3-S06 | Frontend workflow version editor (JSON + step summary, validate button, publish button, error highlighting) | Vitest tests pass |
| P3-S07 | Labs + ADR-003 + progress log | recorded in `docs/lab-notes/phase-03.md` and `docs/adr/ADR-003-custom-state-machine.md` |

## Files
```text
app/domain/{workflow_definition,graph_validator}.py
app/modules/workflows/{schemas,repository,service,router}.py   # modified
tests/unit/{test_workflow_definition,test_graph_validator,test_graph_properties}.py
tests/integration/test_workflow_versions.py
frontend/src/features/workflows/{WorkflowDetailPage,VersionEditor,ValidationErrors}.tsx
docs/lab-notes/phase-03.md   docs/adr/ADR-003-custom-state-machine.md
```

## Domain contracts

### Canonical JSON and Checksum (`app/domain/workflow_definition.py`)
```python
def canonical_json(definition: dict[str, Any]) -> bytes:
    return orjson.dumps(definition, option=orjson.OPT_SORT_KEYS)


def definition_checksum(definition: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(definition)).hexdigest()
```

### Graph Validator (`app/domain/graph_validator.py`)
```python
@dataclass(frozen=True)
class ValidationIssue:
    code: str  # one of the §7 graph/validation error codes
    field: str  # e.g. "steps.classify.next" or "steps.crm.config.body"
    message: str
    step_ids: list[str] = field(default_factory=list)


def validate_definition(
    raw: dict[str, Any],
    *,
    allowed_hosts: set[str] | None = None,
    credential_scopes: dict[uuid.UUID, set[str]] | None = None,
    known_prompt_templates: set[str] | None = None,
) -> list[ValidationIssue]: ...
```
Validation rules executed in deterministic order:
1. **Schema check (`INVALID_STEP_CONFIG`):** `schema_version == 1`, `1 <= len(steps) <= 50`, unique step `id` matching `^[a-z][a-z0-9_]{0,39}$`, `inputs_schema` is a valid Draft 2020-12 JSON Schema object of size ≤ 4 KB and depth ≤ 4, each step's `config` matches its step type rules in `spec/00-global.md` §5 with `extra="forbid"`.
2. **Missing step references (`GRAPH_MISSING_STEP`):** `start` must exist in `steps`; every `next`, `branches[].next`, and `else` (when not `null`) must exist in `steps`.
3. **Reachability (`GRAPH_UNREACHABLE_STEP`):** BFS/DFS from `start`. Any step not visited is reported (sorted by `id`).
4. **Cycle detection (`GRAPH_CYCLE`):** Three-color DFS (`WHITE`, `GRAY`, `BLACK`) from `start`. On back-edge to a `GRAY` node, extract the cycle path `u -> ... -> v -> u` and report `ValidationIssue(code="GRAPH_CYCLE", field="steps", message=..., step_ids=cycle_nodes)`. Also verify at least one step has a `null` transition (terminating path).
5. **Dominator / ancestry check for templates (`UNKNOWN_REFERENCE`):**
   - Extract all `{{ ... }}` placeholders from a step's `config`.
   - Placeholder syntax: `inputs.<prop>(.<rest>)*` or `steps.<step_id>.output(.<rest>)*`. Anything else → `UNKNOWN_REFERENCE`.
   - For `inputs.<prop>`, `<prop>` must exist in `inputs_schema.properties` (when `inputs_schema.additionalProperties` is `false`).
   - For `steps.<ref_id>.output...`, `<ref_id>` must **strictly dominate** the current step (every path from `start` to the current step must pass through `<ref_id>`). Compute dominators via standard iterative dataflow on the DAG: $\text{Dom}(n) = \{n\} \cup \bigcap_{p \in \text{pred}(n)} \text{Dom}(p)$. If `<ref_id> not in Dom(step) - {step}` → `UNKNOWN_REFERENCE`.
6. **Type compatibility (`TYPE_MISMATCH`):**
   - In `condition` branches, if `left` references `steps.<id>.output.label` of an `llm_classify` step and `op` is `eq`/`neq` with a string literal `right`, `right` must be in that classify step's `labels`.
   - If `op` is `gt|gte|lt|lte` and one side is a string literal → `TYPE_MISMATCH`.
7. **Tool & permission policy (`FORBIDDEN_TOOL_PERMISSION`):**
   - For `http_request`: URL must be `https://` with an explicit hostname (no userinfo, no IP literal when `EGRESS_BLOCK_PRIVATE` is true). Header keys `Authorization`, `Cookie`, `Proxy-Authorization`, `Host` (case-insensitive) are forbidden in `config.headers`.
   - If `allowed_hosts` is provided (at publish time, union of `EGRESS_ALLOWED_HOSTS` and referenced credential's `allowed_hosts`), the URL hostname must be in `allowed_hosts`.
8. **Irreversible tool gate (`APPROVAL_REQUIRED_FOR_IRREVERSIBLE`):**
   - For `http_request` with `effect == "write"`: if the referenced credential has `"irreversible"` in `permission_scopes` (or if no credential is set and `effect == "write"` requires approval by policy), there must exist an `approval` step in $\text{Dom}(\text{step}) \setminus \{\text{step}\}$.

When `validate_definition` returns issues on `/versions` publish or `/validate`, the first issue's `code` is used as the top-level Problem Details `code`, and all issues are returned in `errors`.

## API contracts
| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `POST /v1/workflows/{id}/versions` | `{"definition": <object>, "from_version"?: int}` | 201 `WorkflowVersion` (`status="draft"`, `version = max(version)+1` or `1`) | 404; 403; 409 `DRAFT_EXISTS` if a draft already exists for this workflow; 422 if structural JSON is not an object |
| `PUT /v1/workflows/{id}/versions/{n}` | `{"definition": <object>}` | 200 `WorkflowVersion` (updates draft in place) | 404; 403; 409 `INVALID_STATE_TRANSITION` if version `n` is already `published` |
| `GET /v1/workflows/{id}/versions` | `limit`, `cursor` | 200 page of `WorkflowVersionSummary` (omits `definition_json`) | 404 |
| `GET /v1/workflows/{id}/versions/{n}` | — | 200 `WorkflowVersion` (includes `definition_json`) | 404 |
| `POST /v1/workflows/{id}/validate` | `{"definition": <object>}` | 200 `{"valid": bool, "checksum": str\|null, "errors": [ValidationIssue]}` | 404; 403 |
| `POST /v1/workflows/{id}/publish` | `{"version"?: int}` (defaults to current draft version) | 200 `WorkflowVersion` (`status="published"`, `checksum`, `published_at`; also sets `workflows.current_version_id`) | 404; 403; 409 `INVALID_STATE_TRANSITION` if already published or archived; 422 (`GRAPH_CYCLE`, etc.) if `validate_definition` returns issues |

`WorkflowVersion`: `{"id","workflow_id","org_id","version","status","definition_json","schema_version","checksum","created_by","created_at","published_at"}`.
Publishing runs in one transaction: lock the `workflows` row `FOR UPDATE`, load the target `workflow_versions` row, run `validate_definition`, compute `checksum`, `UPDATE workflow_versions SET status='published', checksum=:c, published_at=now()`, `UPDATE workflows SET current_version_id=:vid, updated_at=now()`, commit.

## Test cases
| ID | File | Given / When / Then |
|---|---|---|
| P3-T01 | test_workflow_definition | Canonical JSON produces identical SHA-256 regardless of dict key insertion order |
| P3-T02 | test_graph_validator | Valid 5-step support-ticket DAG from `spec/00-global.md` §5 passes with 0 issues |
| P3-T03 | test_graph_validator | Direct self-loop (`a -> a`) and 3-node cycle (`a -> b -> c -> a`) return `GRAPH_CYCLE` with the cycle step IDs |
| P3-T04 | test_graph_validator | Orphan step not reachable from `start` returns `GRAPH_UNREACHABLE_STEP` |
| P3-T05 | test_graph_validator | `next` pointing to non-existent step returns `GRAPH_MISSING_STEP` |
| P3-T06 | test_graph_validator | Step referencing `{{ steps.later.output.x }}` or a sibling branch step (not a strict dominator) returns `UNKNOWN_REFERENCE` |
| P3-T07 | test_graph_validator | Step referencing `{{ inputs.missing }}` when `additionalProperties=false` returns `UNKNOWN_REFERENCE` |
| P3-T08 | test_graph_validator | `condition` comparing `llm_classify` output to a label not in `labels` returns `TYPE_MISMATCH` |
| P3-T09 | test_graph_validator | `http_request` with `http://` URL or `Authorization` header returns `FORBIDDEN_TOOL_PERMISSION` / `INVALID_STEP_CONFIG` |
| P3-T10 | test_graph_validator | Irreversible `http_request` without dominating `approval` step returns `APPROVAL_REQUIRED_FOR_IRREVERSIBLE`; with dominating `approval` on all paths passes |
| P3-T11 | test_graph_properties | Hypothesis: generate random directed graphs (1–25 nodes); `validate_definition` never raises an unhandled exception; every accepted graph has a valid topological order and every node is reachable from `start` |
| P3-T12 | test_workflow_versions | Create draft v1 → 201; creating second draft while v1 is draft → 409 `DRAFT_EXISTS`; `PUT` updates v1 draft → 200 |
| P3-T13 | test_workflow_versions | Publish invalid draft (cycle) → 422 `GRAPH_CYCLE`, remains `draft`, `current_version_id` remains `null` |
| P3-T14 | test_workflow_versions | Publish valid draft v1 → 200, `status="published"`, `checksum` set, `workflows.current_version_id == v1.id` |
| P3-T15 | test_workflow_versions | `PUT /v1/workflows/{id}/versions/1` after v1 is published → 409 `INVALID_STATE_TRANSITION`; creating new draft creates `version=2` |
| P3-T16 | test_workflow_versions | Cross-tenant user calling `validate` or `publish` on org A workflow → 404 |

## Frontend
Routes added: `/orgs/:orgId/workflows/:workflowId` (`WorkflowDetailPage`).
- Displays published version badge, version history list, and the `VersionEditor` for the current draft (or a "New Draft from latest" button if no draft exists).
- `VersionEditor`: `<textarea>` (monospace, accessible label "Workflow definition JSON") + parsed step list preview (step ID, type, transitions) + "Validate" button (`POST /validate`) + "Save draft" (`PUT`) + "Publish" (`POST /publish`, only for `owner`/`admin`).
- Validation issues render in an accessible `<ul role="alert">` showing `code`, `field`, `message`, and `step_ids`.
- Frontend tests: `P3-F01` renders step preview from valid JSON; `P3-F02` shows validation issues from `/validate`; `P3-F03` disables "Publish" when role is `operator`/`viewer`; `P3-F04` transitions draft to published badge on publish.

## Labs (`docs/lab-notes/phase-03.md`)
1. Construct a diamond DAG (`start -> [b, c] -> join`) where `join` references `{{ steps.b.output.x }}`. Show why `b` does **not** dominate `join` (path `start -> c -> join` skips `b`) and confirm `validate_definition` rejects it with `UNKNOWN_REFERENCE`.
2. Attempt to mutate a published `workflow_versions` row directly via SQL (`UPDATE workflow_versions SET definition_json = '{}' WHERE status = 'published'`) and record the PostgreSQL trigger error `P0001`.
3. Run 500 Hypothesis examples (`--hypothesis-seed=0`) and record runtime and any edge case found.

## Verification commands
```bash
ruff check . && ruff format --check . && mypy app && pytest -q
python scripts/export_openapi.py && git diff --exit-code openapi.json
cd frontend && npm run gen:api && npm run lint && npm run typecheck && npm test && npm run build
```

## Done when
- [ ] P3-T01…T16 and P3-F01…F04 pass.
- [ ] Labs 1–3 recorded; ADR-003 written; Phase 3 PDF built.

## Agent brief
**Do:** keep `workflow_definition.py` and `graph_validator.py` 100% pure (zero imports from `fastapi`, `sqlalchemy`, or `app.infrastructure`). **Don't:** execute steps yet (Phase 4) or allow cycles. **Stop and report** if any step config rule in `spec/00-global.md` §5 is ambiguous.
