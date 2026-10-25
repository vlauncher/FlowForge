# FlowForge Architecture Diagrams

This document contains the structural C4 diagrams, Entity-Relationship Diagram (ERD), and core sequence diagrams for the FlowForge platform.

---

## 1. C4 Context Diagram (System Context)

```mermaid
flowchart TD
    User["Platform Developer / Operations Engineer"]
    ExtProvider["External LLM Providers (OpenRouter, Anthropic, OpenAI)"]
    ExtSaaS["Third-Party SaaS APIs (Stripe, GitHub, Jira)"]
    InboundWebhook["Inbound Webhook Senders (Stripe, GitHub)"]

    subgraph FlowForge["FlowForge Automation Platform"]
        FFApp["FlowForge Platform (API, Workers, Engine, UI)"]
    end

    User -->|"Manages workflows, inspects runs, approves actions"| FFApp
    InboundWebhook -->|"Sends signed webhook events"| FFApp
    FFApp -->|"Dispatches completions and tool calls"| ExtProvider
    FFApp -->|"Performs validated external HTTP calls"| ExtSaaS
```

---

## 2. C4 Container Diagram (Architecture Topology)

```mermaid
flowchart TD
    subgraph Clients
        Browser["React 19 SPA (Vite, TypeScript, Tailwind)"]
        CLI["FlowForge Admin CLI & Scripts"]
        WebhookClient["External Webhook Emitter"]
    end

    subgraph Platform Edge & Application
        Nginx["Nginx Reverse Proxy (SSL, CSP, Compression)"]
        FastAPI["FlowForge FastAPI Monolith (ASGI)"]
    end

    subgraph Messaging & Background Execution
        RabbitMQ["RabbitMQ Message Broker (AMQP 0-9-1)"]
        WorkerFleet["FlowForge Runner Workers (Celery / Async Tasks)"]
        Sweeper["Recovery Sweeper Process"]
    end

    subgraph Persistence & Infrastructure
        Postgres[("PostgreSQL 16 (JSONB, Outbox, FOR UPDATE locks)")]
        Prometheus["Prometheus Metric Collector"]
        OTelCollector["OpenTelemetry Collector & Tracer"]
    end

    Browser -->|"HTTPS / REST / JSON"| Nginx
    CLI -->|"HTTPS / REST / JSON"| Nginx
    WebhookClient -->|"HMAC-Signed POST"| Nginx
    Nginx --> FastAPI

    FastAPI -->|"Read/Write (ACID)"| Postgres
    FastAPI -->|"Transactional Outbox Insert"| Postgres
    FastAPI -->|"Dispatch / Publish"| RabbitMQ

    RabbitMQ -->|"Consume RunExecutionRequested"| WorkerFleet
    WorkerFleet -->|"Claim Lease / Log Effects"| Postgres
    Sweeper -->|"Sweep Stale Leases / Expired Approvals"| Postgres
    Sweeper -->|"Re-enqueue RunResumeRequested"| Postgres

    FastAPI -->|"Expose /metrics"| Prometheus
    WorkerFleet -->|"Telemetry traces"| OTelCollector
```

---

## 3. C4 Component Diagram (FastAPI Modular Monolith)

```mermaid
flowchart TD
    subgraph API Modules
        AuthRouter["Auth Router (/v1/auth)"]
        OrgRouter["Organizations Router (/v1/organizations)"]
        WorkflowRouter["Workflows Router (/v1/workflows)"]
        RunRouter["Executions Router (/v1/runs)"]
        ApprovalRouter["Approvals Router (/v1/approvals)"]
        TriggerRouter["Triggers Router (/v1/triggers, /v1/webhooks)"]
        UsageRouter["Usage & Budget Router (/v1/usage)"]
        AuditRouter["Audit Router (/v1/audit)"]
    end

    subgraph Core Services & Cross-Cutting
        RateLimiter["RateLimitMiddleware (Sliding Window)"]
        SecurityValidator["SSRF Egress Validator & IP Pinner"]
        BudgetManager["Two-Phase Budget Reservation Manager"]
        AuditLogger["Audit Event Logger"]
        HMACVerifier["Webhook HMAC-SHA256 Verifier"]
    end

    subgraph Persistence Repositories
        WorkflowRepo["WorkflowRepository"]
        RunRepo["ExecutionRepository"]
        ToolLedger["ToolEffectsRepository"]
        BudgetRepo["BudgetReservationRepository"]
    end

    WorkflowRouter --> WorkflowRepo
    RunRouter --> RunRepo
    RunRouter --> BudgetManager
    ApprovalRouter --> RunRepo
    TriggerRouter --> HMACVerifier
    TriggerRouter --> RunRepo

    RunRepo --> ToolLedger
    BudgetManager --> BudgetRepo
```

---

## 4. Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    organizations ||--o{ users : "has members"
    organizations ||--o{ workflows : "owns"
    organizations ||--o{ integration_credentials : "owns"
    organizations ||--o{ triggers : "owns"
    organizations ||--o{ workflow_runs : "executes"
    organizations ||--o{ budget_reservations : "holds"
    organizations ||--o{ usage_records : "incurs"
    organizations ||--o{ audit_events : "generates"

    workflows ||--o{ workflow_versions : "versions"
    workflow_versions ||--o{ workflow_runs : "pins"
    triggers ||--o{ workflow_runs : "initiates"

    workflow_runs ||--o{ step_attempts : "attempts"
    workflow_runs ||--o{ approval_requests : "requires"
    workflow_runs ||--o{ tool_effects : "ledgers"
    workflow_runs ||--o{ budget_reservations : "reserves"

    organizations {
        uuid id PK
        string name
        string tier
        bigint budget_limit_micro_usd
        timestamp created_at
    }

    workflows {
        uuid id PK
        uuid org_id FK
        string display_name
        boolean is_active
    }

    workflow_versions {
        uuid id PK
        uuid workflow_id FK
        int version
        jsonb definition_json
        string checksum
        timestamp published_at
    }

    workflow_runs {
        uuid id PK
        uuid org_id FK
        uuid version_id FK
        string state
        string lease_owner
        timestamp lease_expires_at
        int attempt_epoch
        jsonb context
    }

    tool_effects {
        uuid id PK
        uuid org_id FK
        uuid run_id FK
        string step_id
        string idempotency_key
        string state
        string provider
    }

    budget_reservations {
        uuid id PK
        uuid org_id FK
        uuid run_id FK
        bigint amount_micro_usd
        string state
    }
```

---

## 5. Sequence Diagram: Run Execution & Durable State Transitions

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI API
    participant DB as PostgreSQL
    participant Worker as Background Worker
    participant Ext as External Service

    Client->>API: POST /v1/workflows/{id}/runs
    API->>DB: Check & Reserve Budget (SELECT FOR UPDATE organizations)
    API->>DB: INSERT workflow_runs (state='QUEUED') + outbox_events
    API-->>Client: 201 Created (run_id)

    Worker->>DB: Poll / Claim Run (UPDATE ... WHERE state='QUEUED' FOR UPDATE SKIP LOCKED)
    DB-->>Worker: Run Claimed (attempt_epoch=1, lease_expires_at=+30s)

    loop Heartbeat Loop
        Worker->>DB: UPDATE workflow_runs SET heartbeat_at=now(), lease_expires_at=now()+30s
    end

    Worker->>DB: INSERT tool_effects (state='INTENDED', idempotency_key)
    Worker->>Ext: POST /v1/action (Idempotency-Key header)
    Ext-->>Worker: 200 OK (external_ref)
    Worker->>DB: UPDATE tool_effects SET state='COMMITTED', external_ref

    Worker->>DB: Settle Budget Reservation (SETTLED) + INSERT usage_records
    Worker->>DB: UPDATE workflow_runs SET state='SUCCEEDED', lease_owner=NULL
```

---

## 6. Sequence Diagram: Kill-Worker Crash Recovery

```mermaid
sequenceDiagram
    autonumber
    participant W1 as Worker 1
    participant DB as PostgreSQL
    participant Sweeper as Recovery Sweeper
    participant W2 as Worker 2
    participant Ext as External API

    W1->>DB: Execute Step 1: ToolEffect COMMITTED
    Note over W1: Worker 1 forcefully crashes (SIGKILL / OOM)
    Note over DB: Run remains RUNNING, lease_expires_at passes

    Sweeper->>DB: SELECT runs WHERE state='RUNNING' AND lease_expires_at < now()
    Sweeper->>DB: INSERT outbox_events (RunResumeRequested)

    W2->>DB: Claim Run (UPDATE attempt_epoch=attempt_epoch+1)
    DB-->>W2: Claimed (attempt_epoch=2)
    W2->>DB: Check tool_effects for Step 1
    Note over W2: Step 1 already COMMITTED -> SKIP wire call!
    W2->>Ext: Execute Step 2: POST call (Wire call executed once)
    Ext-->>W2: 200 OK
    W2->>DB: Mark Step 2 COMMITTED
    W2->>DB: UPDATE workflow_runs SET state='SUCCEEDED'
```
