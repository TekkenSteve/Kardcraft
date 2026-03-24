# Task Orchestrator Architecture (DDD)

## Purpose
This document defines the non-negotiable architecture boundaries for `backend/task-orchestrator`.
Any new feature must follow this document to avoid architecture drift.

## Core Principles
1. Rich Domain Model: business rules live in domain entities/aggregates, not in application services.
2. Layered Architecture: `domain -> application -> infrastructure` (dependency direction only inward).
3. Immutable Value Objects: value objects are immutable (`struct` + private fields + constructor + getters only).
4. Dependency Inversion: repository interfaces are declared in domain, implemented in infrastructure.
5. Domain Events on State Changes: every state transition must raise domain events.
6. Domain Purity: domain must not import DB/HTTP/Redis/Temporal/logging frameworks.

## Directory Contract

```text
internal/
  domain/task/
    aggregate.go      # Task aggregate root (Start/Complete/Fail and invariants)
    entity.go         # Child entities (e.g. Step)
    valueobject.go    # Immutable value objects (TaskID, StepID, Status)
    repository.go     # Repository + publisher interfaces
    events.go         # Domain event definitions
  application/
    service.go        # Use-case orchestration only (<100 lines per use case method)
  infrastructure/
    persistence/
      task_repo.go    # Repository implementations (in-memory/DB)
cmd/
  orchestrator/
    main.go           # Composition root / wiring
```

## Layer Responsibilities

### 1) Domain Layer (`internal/domain/task`)
- Owns all business invariants and state transition rules.
- Exposes aggregate methods such as `Task.Start()`, `Task.Complete()`, `Task.Fail()`.
- Stores and exposes uncommitted domain events (`PullEvents()`).
- Defines repository abstractions used by upper layers.

Must do:
- Validate transition legality inside aggregate/entity methods.
- Keep value objects immutable.
- Emit domain events whenever status changes.

Must not do:
- Direct DB queries.
- HTTP/gRPC calls.
- Logging, metrics, tracing SDK calls.
- Reading env/config files.

### 2) Application Layer (`internal/application`)
- Coordinates use cases; does not implement business rules.
- Typical method flow:
  1. Load aggregate from repository.
  2. Call aggregate behavior.
  3. Persist aggregate.
  4. Publish pulled domain events.

Constraints:
- Keep each use-case method concise (target: <100 lines).
- No duplicate business validation that already exists in domain.

### 3) Infrastructure Layer (`internal/infrastructure`)
- Implements domain interfaces for persistence/event publishing.
- Handles technical concerns (SQL, transaction, serialization, adapters).
- Can depend on external libraries and frameworks.

Constraints:
- Never move business rules from domain to infrastructure.
- Keep translation/mapping explicit between storage model and domain model.

## Aggregate Rules (Task)

`Task` is the aggregate root. All state transitions pass through it.

Mandatory rules:
1. Only aggregate methods may mutate task status.
2. Illegal transitions must return domain errors.
3. Each successful transition must append exactly one matching domain event.
4. Aggregate exposes immutable snapshots/read methods to callers.

Example transition policy (baseline):
- `pending -> running` via `Start()`
- `running -> completed` via `Complete()`
- `running -> failed` via `Fail(reason)`
- Any other transition is rejected.

## Value Object Rules
- Constructor validates invariants and returns error on invalid input.
- Fields are private (lowercase) and not directly writable.
- Equality is by value (`Equal()` method), not pointer identity.

## Error and Event Conventions
- Domain errors are typed/sentinel errors in domain package.
- Domain events include at least:
  - event id
  - aggregate id (`TaskID`)
  - event type
  - occurred-at timestamp
- Event publishing is best-effort defined by use case contract; retry policy belongs to infrastructure/application policy, not domain.

## Adding New Features (Checklist)
1. Define/extend domain behavior first (aggregate/entity/value object).
2. Add/adjust domain events for new state changes.
3. Update domain interfaces only if persistence/event contracts change.
4. Update application service orchestration.
5. Implement infrastructure adapters.
6. Add tests:
   - Domain unit tests for business rules.
   - Application tests for orchestration.
   - Infrastructure tests for adapter behavior.

## Anti-Patterns (Do Not Merge)
- Putting `if business condition` logic inside application service or repository.
- Domain importing `database/sql`, `net/http`, Redis/Temporal SDK, logger packages.
- Mutable value objects (public fields/setters).
- Updating state without generating corresponding domain event.
- Fat `main.go` containing business orchestration.

## Enforcement Suggestions
- Add CI checks:
  - `go test ./...`
  - static import checks (domain package forbidden imports list)
- Code review gate:
  - Every PR touching task status must show aggregate method change + domain event.

## Migration Note
Legacy implementation is preserved at:
- `backend/task-orchestrator-bak`

New development should target only:
- `backend/task-orchestrator`

## Session Storage Runtime Policy

The runtime storage model for session APIs is:

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

## `task-orchestrator-bak` Capability Matrix

### Existing capability groups
1. Task API:
- Create/list/get tasks
- Pause/resume/cancel/control-state
- Batch/template task creation

2. Workflow runtime:
- Temporal workflow execution
- Workflow status/cancel/history query API

3. Event and stream:
- `/api/v1/events` intake
- `/api/v1/stream/sse` push
- Redis Stream `stream:events:{workflow_id}` bridge

4. Session contract:
- List/get/update/delete session
- Conversation/timeline/history/state/workspace views
- Session/task/event persistence in Postgres

5. Ancillary interfaces:
- card templates
- cards bulk/edit/lock
- file upload session APIs
- agents/health/root

### Gaps and problems in `-bak`
1. Domain logic and infra logic were coupled in handler layer.
2. Temporal, Redis, Postgres behavior had scattered ownership and duplicated status updates.
3. Session history correctness depended on ad-hoc event paths.
4. In-memory fallback paths made data consistency nondeterministic.
5. Pause/resume/cancel semantics were partially implemented but not consistently observable.

## Database Schema Governance Boundary

1. `backend/database/migrations` is the only schema authority.
2. Service runtime must not execute schema-mutating DDL (`CREATE/ALTER/DROP`) in startup path or request path.
3. `task-orchestrator` startup validates required migration version via `kc_schema_migrations` and fails fast when missing.
4. Service-local init SQL is non-authoritative and must not be used as long-term migration mechanism.

## Code Review Checklist Addendum

1. No runtime DDL strings added in Go/Python/TS service code.
2. Schema changes are accompanied by migration files under `backend/database/migrations`.
3. `scripts/check_no_runtime_ddl.sh` and `scripts/check_schema_drift.sh` pass before merge.

## Refactor Plan (Current Baseline)

1. Keep interface compatibility:
- Preserve all `-bak` routes and response contracts where upstream depends on them.

2. DDD separation:
- Domain aggregate owns task state transitions and event emission.
- Application service only orchestrates repo load/save + event publish.
- Infrastructure adapts HTTP/Temporal/Redis/Postgres.

3. Storage policy:
- Postgres = source of truth for `kc_sessions/kc_tasks/kc_events`.
- Redis = hot cache + realtime transport.
- No in-memory fallback for session contract read/write paths.

4. Hot/cold session strategy:
- Active session cache in Redis.
- Inactivity judged by `last_activity_at` + `SESSION_ACTIVE_WINDOW_SECONDS`.
- Background cooldown only evicts Redis hot keys.
- Reactivation is read-through from Postgres and cache repopulation.

5. Cleanup consistency:
- Session delete clears Postgres rows and session-scoped Redis keys.
- Task/session mapping keys cleaned on session deletion path.

6. Realtime continuity:
- SSE must merge in-memory timeline and Redis Stream events.
- Stream events are persisted into Postgres timeline so history survives reconnect/restart.

7. Event contract (source-side governance):
- Agent workflow only emits meaningful lifecycle events: `NODE_STARTED`, `NODE_COMPLETED`, `NODE_FAILED`, plus coarse `WORKFLOW_PROGRESS`.
- Do not emit raw internal/tool noise and do not rely on downstream filtering as primary control.
- Event payload must include `workspace_id` when available; current runtime may pass `session_id` as workspace credential, but contract remains workspace-based.
- Timeline/SSE should treat `workspace_id` as isolation boundary abstraction, not a hardcoded session-only concept.

## Enterprise Improvements (Next-step Ready)

1. Redis HA:
- Prefer Redis Sentinel or Redis Cluster; avoid single instance in production.

2. Postgres HA:
- Primary/replica with WAL archiving and PITR for disaster recovery.

3. Event durability:
- Add outbox table for workflow/session events to remove dual-write race risk.

4. Observability:
- Add metrics for cache hit rate, SSE backlog lag, Temporal start failure rate, session cooldown volume.

5. Idempotency and replay:
- Make event ingestion idempotent by `(workflow_id, stream_id)` unique key.
- Add replay API for workflow stream from persisted timeline.
