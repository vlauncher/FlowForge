# Problem Brief & Product Requirements Document

## 1. Executive Summary & Problem Statement
Modern automated operations require workflows that combine external SaaS APIs, human approvals for sensitive actions, and generative AI reasoning. However, typical "LLM wrappers" and script-based automations fail catastrophically in real-world environments:
- External network requests time out or fail intermittently.
- Background worker processes crash mid-execution, losing in-flight state.
- Unreliable LLM completions return unparsable schemas or hallucinated tool parameters.
- Duplicate webhooks cause double billing, duplicate CRM updates, and data corruption.
- Multi-tenant systems lack strict object-level isolation and auditable trails for human sign-offs.

**FlowForge** is an organization-scoped, durable workflow automation platform that solves these distributed systems challenges. It enables users to define versioned directed acyclic graph (DAG) automations, executes them reliably across asynchronous worker processes via a transactional outbox, pauses safely for human-in-the-loop approvals, gates external side effects with an idempotent ledger, and validates untrusted AI steps before committing any state.

## 2. Target Personas & User Stories

### Persona 1: Workflow Owner (Operations Lead)
- *Story 1.1:* As an Operations Lead, I want to define multi-step DAG workflows via validated schema definitions, so that routine business processes run consistently without bespoke scripting.
- *Story 1.2:* As an Operations Lead, I want published workflow versions to be completely immutable, so that ongoing or historical runs cannot have their business logic altered unexpectedly.
- *Story 1.3:* As an Operations Lead, I want to inspect a visual and tabular step timeline of every run, so that I can determine why an automation succeeded, failed, or paused.

### Persona 2: Organization Administrator
- *Story 2.1:* As an Org Admin, I want to manage members with role-based access control (`owner`, `admin`, `operator`, `reviewer`, `viewer`), so that least-privilege principles are strictly maintained.
- *Story 2.2:* As an Org Admin, I want to configure per-organization spending budgets and concurrent run limits, so that our team never incurs surprise API bills or overwhelms downstream services.
- *Story 2.3:* As an Org Admin, I want to manage and rotate allowlisted integration credentials securely, so that secrets are encrypted at rest and never exposed to unprivileged users or model prompts.

### Persona 3: Workflow Operator / Reviewer
- *Story 3.1:* As a Reviewer, I want a centralized approval inbox with clear contextual summaries, so that I can review and approve or reject sensitive, irreversible operations before they execute.
- *Story 3.2:* As an Operator, I want to manually trigger workflow runs with validated JSON inputs and unique idempotency keys, so that accidental double-clicks never create duplicate runs.
- *Story 3.3:* As an Operator, I want to safely cancel running executions or retry failed runs from their point of failure, so that I can recover from transient third-party outages without duplicating committed side effects.

### Persona 4: Integration Developer
- *Story 4.1:* As an Integration Developer, I want an allowlisted HTTP tool adapter with automatic exponential backoff, jitter, and circuit breaking, so that upstream 503s and 429s are handled gracefully without manual intervention.
- *Story 4.2:* As an Integration Developer, I want signed webhook endpoints with HMAC-SHA256 verification and timestamp windows, so that third-party events (e.g. Stripe, Zendesk) can trigger workflows securely without replay attacks.
- *Story 4.3:* As an Integration Developer, I want structured JSON output validation for all LLM steps with strict Draft 2020-12 schemas, so that model output is treated as untrusted input and sanitized before persistence.

### Persona 5: Platform Administrator / SRE
- *Story 5.1:* As a Platform Admin, I want end-to-end distributed tracing across API, broker, workers, and tool adapters, so that I can diagnose cross-process latency bottlenecks in seconds.
- *Story 5.2:* As an SRE, I want Prometheus metrics tracking queue lag, oldest queued run age, and outbox backlogs, so that I can detect stuck queues even when HTTP health probes return 200.
- *Story 5.3:* As an SRE, I want a recovery sweeper that automatically reclaims abandoned leases when worker nodes crash, so that no job silently disappears without human escalation.

## 3. Explicitly Out of Scope (MVP)
To maintain architectural focus and security boundaries, the following capabilities are **explicitly forbidden** from the MVP:
1. Arbitrary user-supplied Python, bash, or code execution in worker processes.
2. Unrestricted, generic `fetch_url` tools without strict hostname allowlists, egress network filters, and DNS-rebinding defenses.
3. Unbounded recursive agents or autonomous browsing loops.
4. Drag-and-drop visual node canvas (the MVP provides a structured JSON/form editor and step preview).
5. Public tool marketplace and multi-tenant marketplace billing.
