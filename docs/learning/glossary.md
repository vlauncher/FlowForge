# Glossary

| Term | Meaning in FlowForge |
|---|---|
| Organization (tenant) | Owner of workflows, credentials, runs and budgets |
| Workflow | A named automation owned by an organization |
| WorkflowVersion | Immutable published definition. Edits create a new version |
| Run | One execution of a pinned workflow version |
| Step / StepAttempt | A unit in the graph / one try of that unit |
| Idempotency key | Client or system token ensuring a repeated request has one effect |
| Outbox | Table of events written in the same transaction as state, published later |
| Lease / heartbeat | Time-limited claim on a run by a worker, renewed while alive |
| At-least-once delivery | A message may be delivered more than once, so consumers must be idempotent |
| Tool effect | An external side effect (CRM ticket, email) recorded in a ledger |
| Approval | A human decision bound to run, step, version, actor and time window |
| Invariant | A rule that must always hold |
| ADR | Architecture Decision Record |
| SLI / SLO | Measured indicator / target for it |
| Problem Details | RFC 9457 standard error body |
