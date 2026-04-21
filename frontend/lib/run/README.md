# Run Actor System Boundaries

`frontend/lib/run` is the only run-domain state ownership boundary.

## Modules

- `app-machine.ts`: root `AppActor`, lifecycle owner for child registries.
- `session-registry-machine.ts`: session index + active-session selection + promotion mapping.
- `session-machine.ts`: per-session lifecycle state machine (`idle/hydrating/ready/running/paused/completing/terminal`).
- `stream-actor.ts`: SSE transport effect actor; decodes wire events into `RunDomainEvent`.
- `session-bundle-loader-machine.ts`: bootstrap loader actor for session/conversation/timeline/history.
- `workspace-loader-machine.ts`: workspace projection loader actor.
- `task-control-machine.ts`: pause/resume/cancel control-state effect actor.
- `domain-events.ts`: canonical `RunDomainEvent` parsing and projection boundary.
- `system.tsx`: React adapter layer (selectors + command dispatch).
- `types.ts`: run-domain data contracts and session key helpers.

## Rules

- UI components must consume actor selectors/view models only.
- Raw wire event strings must not pass into UI domain logic.
- Session promotion must go through registry `PROMOTE_SESSION` only.
- No Redux run-domain ownership is allowed.
