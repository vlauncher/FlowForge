# ADR-002: Multi-Tenant Data Isolation Strategy

Status: accepted
Date: 2026-10-25

## Context / requirements and constraints
FlowForge is a multi-tenant workflow orchestration engine where multiple customer organizations share the underlying platform. Strong data isolation between organizations is an absolute requirement: under no circumstances may one organization read, mutate, or detect the existence of another organization's workflows, runs, credentials, or audit logs.

Constraints:
- PostgreSQL 16 relational database.
- Dynamic tenant onboarding without DDL overhead or per-tenant migration lag.
- Keyset cursor pagination over tenant workflows.
- Solo developer maintainability and predictable operational costs.

## Options considered and rejected
1. **Database-per-Tenant:**
   - *Rejected:* High operational overhead. Connection pooling becomes intractable with hundreds of small tenants. Cross-tenant migrations require complex sequential or fan-out orchestration. Extreme resource waste for low-activity tenants.
2. **Schema-per-Tenant (PostgreSQL Search Path):**
   - *Rejected:* Significant Alembic migration complexity (running DDL per schema). Connection pool partitioning per schema exhausts connection limits. Dynamic schema creation introduces DDL locks and schema catalog bloat.
3. **PostgreSQL Native Row-Level Security (RLS) via Session Variables:**
   - *Rejected:* Requires setting transaction-scoped runtime configuration (`SET LOCAL app.current_org_id = ...`) on every pooled connection check-out. Fragile when combined with connection pooling and async event-loop concurrency; easy to leak if a session variable reset is missed.

## Decision and justification
We adopt **Row-Level Tenancy with Mandatory `org_id` Application Partitioning and Defense-in-Depth Enforcement**:
1. **Explicit `org_id` Column on All Tenant Tables:** Every tenant-scoped entity (`workflows`, `workflow_versions`, `runs`, `approvals`, `credentials`, `memberships`) contains a foreign key `org_id UUID REFERENCES organizations(id) ON DELETE CASCADE`.
2. **Keyword-Only Repository Method Contracts:** All repository methods interacting with tenant-scoped tables mandate `*, org_id: UUID` as an explicit, keyword-only parameter. Repository implementations unconditionally include `.where(Model.org_id == org_id)`.
3. **Automated Static AST Analysis:** A dedicated verification tool (`scripts/check_tenant_params.py`) executes during CI to statically parse the repository AST, guaranteeing that all tenant methods take `org_id` and do not allow unscoped querying.
4. **Composite Keyset Indexes:** All high-throughput queries are backed by composite indexes prefixed with `org_id` (e.g., `ix_workflows_org_created_id` on `(org_id, created_at DESC, id DESC)`).
5. **Existence Leak Prevention:** Attempting to access an organization or workflow outside the caller's membership returns HTTP 404 (Not Found) rather than HTTP 403 (Forbidden), preventing organization enumeration.

## Consistency / availability / security / cost consequences
- **Cost & Resource Efficiency:** Near-zero marginal cost per tenant; standard connection pools (`NullPool` in tests, single pool in prod) serve all tenants efficiently.
- **Security:** Layered defense: route dependencies (`get_membership`), repository parameter enforcement, and static AST linting ensure queries cannot omit `org_id`.
- **Operational Simplicity:** Single unified migration runner (`alembic upgrade head`) updates the entire database atomically.

## Failure modes and mitigations
- *Developer omission of `org_id` in new queries:* Prevented by static AST checker in CI (`scripts/check_tenant_params.py`) and mandatory multi-tenant cross-org integration test suite (`tests/integration/test_tenancy.py`).
- *Cross-tenant subquery leaks:* All subqueries and joins on tenant entities must explicitly bind `org_id`.

## Validation experiment
- Verified by static parameter analysis (`test_static_tenant_parameter_check`).
- Verified by cross-tenant query tests where Org A cannot read, list, or mutate Org B workflows (`test_workflow_tenant_isolation` and `test_cannot_get_workflow_from_another_org`).

## Revisit trigger
A tenant requires dedicated physical isolation or customer-managed encryption keys (CMEK) for enterprise compliance (e.g., FedRAMP High, HIPAA dedicated tenancy).
