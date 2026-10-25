# ADR-003: Pure Domain DAG Validator and Deterministic State Machine

Status: accepted
Date: 2026-10-25

## Context / requirements and constraints
FlowForge requires a robust workflow definition and validation engine capable of verifying workflow topology (reachability, cycle freedom, strict dominator ancestry, type compatibility, and security boundaries) **before** execution.

Constraints:
- Published workflow versions must be strictly immutable and cryptographically verifiable (SHA-256 canonical checksum).
- Definitions must execute deterministically without framework-induced side effects or hidden control-flow magic.
- Fast, pure in-memory validation testable with property-based testing (Hypothesis) without database or network I/O.
- Clear separation between definition validation (compile-time) and execution (run-time).

## Options considered and rejected
1. **Adopting LangGraph / Temporal / Airflow SDK as Domain Core:**
   - *Rejected:* Heavy external dependencies. Opaque execution semantics and framework state serialization models complicate ledger-based transactional outbox and auditing. They mix graph authoring with execution runtime concerns.
2. **Dynamic / Runtime Cycle & Ancestry Resolution:**
   - *Rejected:* Validating graphs during execution leads to partial runs failing mid-pipeline after producing irreversible external side effects (e.g., billing, emails, API writes).
3. **Pydantic Validation Alone without Graph Theory:**
   - *Rejected:* Pydantic models validate syntax and field bounds, but cannot determine graph properties like topological reachability, back-edge cycle detection, or strict dominator trees for variable scoping.

## Decision and justification
We implement a **Pure Domain DAG Validator & Deterministic State Machine** ([`app/domain/workflow_definition.py`](../../app/domain/workflow_definition.py) and [`app/domain/graph_validator.py`](../../app/domain/graph_validator.py)):
1. **Zero External I/O in Domain:** The validator imports only standard library and `orjson` / `pydantic`. Zero imports from `fastapi` or `sqlalchemy`.
2. **Canonical JSON Serialization & Checksums:** Definitions are serialized via `orjson.dumps(..., option=orjson.OPT_SORT_KEYS)` and digested with SHA-256. Any modification changes the checksum.
3. **Iterative Dominator Analysis for Variable Scoping:** A step can only reference outputs from steps that **strictly dominate** it ($\text{Dom}(n) = \{n\} \cup \bigcap_{p \in \text{pred}(n)} \text{Dom}(p)$). This guarantees that every execution path reaching the step has already executed the referenced step.
4. **Compile-Time Policy Enforcement:** Security constraints (forbidden headers, HTTPS enforcement, allowlisted hosts, irreversible write approval requirements) are validated at publish time.

## Consistency / availability / security / cost consequences
- **Security:** Irreversible external side effects are guaranteed to have a dominating human approval step prior to execution.
- **Reliability:** 100% of cyclic, unreachable, or malformed graphs are rejected prior to runtime dispatch.
- **Performance:** Validation executes in single-digit milliseconds even for 50-step workflows.

## Validation experiment
- Verified via unit test suite (`P3-T01` to `P3-T10`).
- Validated across 500 generated random graphs via Hypothesis (`P3-T11`).
- Immutability enforced by PostgreSQL trigger `trg_workflow_versions_immutable` (Lab 2).

## Revisit trigger
Introduction of intentional cyclic workflows (e.g. bounded iterative loops with explicit iteration caps) in Phase 10+.
