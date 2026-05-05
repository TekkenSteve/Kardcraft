# Run Actor System Boundaries

`frontend/lib/run` is the only run-domain state ownership boundary.

## Modules

- `session-registry-machine.ts`: session actor registry; each session owns its runtime actor.
- `session-machine.ts`: the only reducer for one conversation runtime: messages, progress, cards, controls, and stream watermark.
- `session-sse-actor.ts`: per-session `fetchEventSource` transport with abortable reconnect.
- `domain-events.ts`: canonical `RunDomainEvent` parsing and projection boundary.
- `system.tsx`: React adapter layer (selectors + command dispatch).
- `types.ts`: run-domain data contracts and session key helpers.

## Rules

- UI components must consume actor selectors/view models only.
- `frontend/app/run-detail` must read runtime state from `useSessionViewModel` only; page-local runtime actors/machines/EventSource are forbidden.
- Chat primary rendering must read from `runMessages` only.
- Run message store is the single rendering source (`status`/`system` included).
- Business loading/streaming visibility and control-button loading must derive from registry run status/runPhase transitions only.
- Server-resource data fetching/cache belongs to TanStack Query (`frontend/app/run-detail`).
- Workspace updates for active runs are event-driven from runtime/SSE; no polling fallback path is allowed.
- Raw wire event strings must not pass into UI domain logic.
- No Redux run-domain ownership is allowed.
- Per-session watermark (`lastEventID`) is owned by `session-machine`; paused sessions freeze the visible watermark until resume.
- SSE reconnect must pass `last_event_id` from the session watermark and resume incrementally, not replay full history.

## Runtime Flow

1. User command emits a session event (`START_WORKFLOW` / `PAUSE` / `RESUME` / `CANCEL`).
2. `session-machine` mutates the session runtime and invokes one `session-sse-actor` while running.
3. `session-sse-actor` streams canonical envelopes and reconnects with `last_event_id`.
4. `session-machine` maps envelope -> domain event -> run state mutation, including pause buffer and watermark guards.
5. UI reads selector snapshots only (`useSessionViewModel`), never raw SSE/polling side channels.
