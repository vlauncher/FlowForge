# ADR-001: Modular monolith with separate API, worker and scheduler processes

Status: proposed
Date: 2026-10-25

## Context / requirements and constraints
Solo developer, portfolio project, strong need for consistent transactions between run state and outbox events. No independent scaling or team-ownership boundaries yet.

## Options considered and rejected
- **Microservices:** rejected. Network boundaries would turn local transactions into distributed ones before there is a reason.
- **Single process doing everything (including `BackgroundTasks`):** rejected. Work is lost on crash and CPU work stalls the API.

## Decision and justification
One repository and codebase organised into modules (`identity`, `organizations`, `workflows`, `executions`, `approvals`, `integrations`, `ai`, `usage`, `audit`, `observability`), run as **separate processes**: API, Celery worker, outbox publisher/reconciler.

## Consistency / availability / security / cost consequences
Strong consistency inside one PostgreSQL database. Simple deployment. Modules can be extracted later if a trigger occurs.

## Failure modes and mitigations
Module boundaries can erode: enforce imports with a lint rule and code review.

## Validation experiment
Phase 4 crash tests show the process split gives recovery that in-process tasks cannot.

## Revisit trigger
A module needs independent scaling, a separate team, or isolation for compliance.
