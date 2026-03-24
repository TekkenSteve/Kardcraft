# Task Orchestrator Interface Compatibility

This file tracks interface coverage for the DDD refactor of `backend/task-orchestrator`.

## Covered Routes

- `GET/POST /api/v1/tasks`
- `POST /api/v1/tasks/batch`
- `GET/POST /api/v1/tasks/template`
- `GET /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/pause`
- `POST /api/v1/tasks/{task_id}/resume`
- `POST /api/v1/tasks/{task_id}/cancel`
- `GET /api/v1/tasks/{task_id}/control-state`

- `POST /api/v1/events`
- `GET /api/v1/stream/sse`

- `GET /api/v1/sessions`
- `GET/PATCH/DELETE /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/conversation`
- `GET /api/v1/sessions/{session_id}/timeline`
- `GET /api/v1/sessions/{session_id}/history`
- `GET /api/v1/sessions/{session_id}/workspace`
- `GET /api/v1/sessions/{session_id}/state`
- `POST /api/v1/sessions/{session_id}/pause`
- `POST /api/v1/sessions/{session_id}/resume`
- `POST /api/v1/sessions/{session_id}/cancel`

- `GET/POST /api/v1/card-templates`
- `GET/PUT/PATCH/DELETE /api/v1/card-templates/{template_id}`
- `GET /api/v1/card-templates/{template_id}/export`
- `POST /api/v1/card-templates/preview`
- `POST /api/v1/card-templates/validate`
- `POST /api/v1/card-templates/required-fields`
- `POST /api/v1/card-templates/precheck`
- `POST /api/v1/card-templates/build-apkg`
- `GET/POST /api/v1/users/me/template-preferences`

- `GET/POST /api/v1/schedules`
- `GET/PUT/DELETE /api/v1/schedules/{schedule_id}`
- `POST /api/v1/schedules/{schedule_id}/pause`
- `POST /api/v1/schedules/{schedule_id}/resume`
- `GET /api/v1/schedules/{schedule_id}/runs`

- `POST /api/v1/cards/{session_id}/bulk`
- `POST/DELETE /api/v1/cards/{session_id}/{card_id}/lock` (compat stub)
- `POST /api/v1/cards/{session_id}/{card_id}/edit` (compat stub)

- `GET /api/v1/workflows/status`
- `POST /api/v1/workflows/cancel`
- `GET /api/v1/workflows/history`

- `POST /api/v1/files/upload/init`
- `POST /api/v1/files/upload/chunk/{upload_id}/{chunk_number}`
- `POST /api/v1/files/upload/complete/{upload_id}`
- `GET /api/v1/files/upload/status/{upload_id}`

- `GET/POST /api/agents`
- `GET /health`
- `GET /health/task-orchestrator`
- `GET /`

## Notes

- Task domain logic is implemented with aggregate methods in `internal/domain/task`.
- Application layer remains orchestration-only (`internal/application/service.go`).
- Infrastructure HTTP layer adapts old interface shapes and maps them to the new domain model.
- Legacy implementation remains at `backend/task-orchestrator-bak` for rollback/reference.
