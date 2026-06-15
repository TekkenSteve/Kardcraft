# Task Orchestrator Architecture (Clean + DDD)

## Purpose
This document defines the non-negotiable architecture boundaries for `backend/task-orchestrator`.
Any new feature must follow this document to avoid architecture drift.

## Core Principles
1. Rich Entity Model: business rules live in entity aggregates, not in usecase/controller.
2. Dependency Direction: `controller -> usecase -> entity` (only inward dependencies).
3. Immutable Value Objects: value objects are immutable (`struct` + private fields + constructor + getters only).
4. Dependency Inversion: external capabilities are expressed as interfaces consumed by usecase.
5. Domain Events on State Changes: every state transition must raise domain events.
6. Entity/Usecase Purity: entity/usecase must not import DB/HTTP/Redis/Temporal/logging frameworks.

## Directory Contract

```text
internal/
  app/
    orchestrator.go   # Orchestrator composition root / wiring
  adapter/
    goagent/          # GoAgent AgentOS adapter boundary
  entity/
    aggregate.go      # Task aggregate root (Start/Complete/Fail and invariants)
    entity.go         # Child entities (e.g. Step)
    valueobject.go    # Immutable value objects (TaskID, StepID, Status)
    repository.go     # Repository + publisher interfaces
    events.go         # Domain event definitions
  usecase/
    service.go        # Task usecase orchestration
    command_service.go # Session/task command orchestration
  controller/restapi/v1/
    server.go         # HTTP transport adapter and route wiring
  controller/temporal/workflows/
    task_workflow.go  # Temporal workflow adapter for card_template tasks
  repo/
    persistent/       # Persistence adapters (in-memory/DB)
    redis/            # Redis adapters
cmd/
  orchestrator/
    main.go           # Process lifecycle
  worker/
    main.go           # Temporal worker lifecycle
```

## Layer Responsibilities

### 1) Entity Layer (`internal/entity`)
- Owns all business invariants and state transition rules.
- Exposes aggregate methods such as `Task.Start()`, `Task.Complete()`, `Task.Fail()`.
- Stores and exposes uncommitted domain events (`PullEvents()`).

Must do:
- Validate transition legality inside aggregate/entity methods.
- Keep value objects immutable.
- Emit domain events whenever status changes.

Must not do:
- Direct DB queries.
- HTTP/gRPC calls.
- Logging, metrics, tracing SDK calls.
- Reading env/config files.

### 2) Usecase Layer (`internal/usecase`)
- Coordinates use-cases; does not implement entity business rules.
- Typical method flow:
  1. Load aggregate/state via interfaces.
  2. Call aggregate/usecase behavior.
  3. Persist state via interfaces.
  4. Publish events / signal runtime via interfaces.

Constraints:
- Keep each use-case method concise.
- No duplicate business validation that already exists in entity.
- Do not import concrete repo/runtime/controller packages.

### 3) Outer Layer (`internal/controller`, `internal/repo`)
- Implements technical adapters for HTTP, SQL, Redis, Temporal.
- Can depend on external libraries and frameworks.

Constraints:
- Never move business rules from entity/usecase to outer layer.
- Keep translation/mapping explicit between transport/storage and entity/usecase models.

### 4) Agent Runtime Boundary
- `internal/usecase` owns Kardcraft-level agent ports: `AgentRuntime`, run requests, runtime events, and control operations.
- GoAgent is an external runtime provider, not a domain dependency.
- Only composition roots and `internal/adapter/goagent` may import `github.com/TekkenSteve/GoAgent/agentos*`.
- No package may import GoAgent internal implementation paths such as `agentfw`, `entity`, `repo`, `pkg`, or `usecase`.
- Kardcraft task, session, template, file policy, and context-envelope semantics are translated at the adapter boundary.

## Aggregate Rules (Task)

`Task` is the aggregate root. All state transitions pass through it.

Mandatory rules:
1. Only aggregate methods may mutate task status.
2. Illegal transitions must return domain errors.
3. Each successful transition must append exactly one matching domain event.
4. Aggregate exposes immutable snapshots/read methods to callers.

## Error and Event Conventions
- Domain errors are typed/sentinel errors in entity/usecase packages.
- Domain events include at least:
  - event id
  - aggregate id (`TaskID`)
  - event type
  - occurred-at timestamp

## Adding New Features (Checklist)
1. Define/extend entity behavior first (aggregate/entity/value object).
2. Add/adjust domain events for new state changes.
3. Update usecase interfaces only if persistence/event/runtime contracts change.
4. Update usecase orchestration.
5. Implement controller/repo adapters.
6. Add tests:
   - Entity unit tests for business rules.
   - Usecase tests for orchestration.
   - Adapter tests for controller/repo behavior.

## Anti-Patterns (Do Not Merge)
- Putting business conditions inside controller/repository adapters.
- Entity/usecase importing `database/sql`, `net/http`, Redis/Temporal SDK, logger packages.
- Mutable value objects (public fields/setters).
- Updating state without generating corresponding domain event.
- Fat transport handlers containing business orchestration.

## Enforcement Suggestions
- CI checks:
  - `go test ./...`
  - `scripts/check_task_orchestrator_architecture.sh`
- Architecture guard:
  - `internal/architecture/import_boundary_test.go` blocks GoAgent internal imports outside the adapter/composition boundary.
- Code review gate:
  - Every PR touching task status must show aggregate/usecase change + event/projection impact.

## Session Storage Runtime Policy

1. Postgres is source of truth:
- `kc_sessions`, `kc_tasks`, `kc_events` are authoritative.
- `/api/v1/sessions/*` read-path must be reconstructable from Postgres alone.

2. Redis is hot cache + realtime layer:
- Hot cache keys: `sess:{user_id}:{session_id}:*`
- Task/session mapping: `task:session:{task_id}`
- Realtime stream: `stream:events:{workflow_id}`
- Workspace cache: `pack:session:{session_id}`

3. Active/inactive automation:
- Active window is time-based (`last_activity_at`).
- Background cooldown worker periodically evicts inactive session hot-cache keys from Redis.
- Re-activation is read-through: cache miss loads from Postgres and repopulates Redis.

4. Delete consistency:
- Session delete must clean both Postgres rows and Redis keys (`sess:*`, `task:session:*`, `pack:session:*` for that session scope).

## Database Schema Governance Boundary

1. `backend/database/migrations` is the only schema authority.
2. Service runtime must not execute schema-mutating DDL (`CREATE/ALTER/DROP`) in startup path or request path.
3. `task-orchestrator` startup validates required migration version via `kc_schema_migrations` and fails fast when missing.
4. Service-local init SQL is non-authoritative and must not be used as long-term migration mechanism.
