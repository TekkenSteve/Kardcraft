# Dormant Table Deprecation Audit

Date: 2026-03-22

## Scope

Candidates:

- `workspaces`
- `workspace_files`
- `workflow_tasks`
- `document_metadata`
- `vector_embeddings`
- `system_metrics`
- `audit_logs`

## Runtime Code Reference Check

Method:

- `rg` scan over `backend/` and `frontend/`
- excluded docs and SQL files to focus on runtime paths

Result:

- No active runtime read/write references found for these tables.

## Data Presence Snapshot

Observed row counts at audit time:

- all candidates are `0` rows in current environment.

## Decision

- Mark deprecated now (`0002_mark_dormant_tables_deprecated.sql`)
- Keep non-destructive during observation window
- Drop only in a later migration after explicit go/no-go gate
