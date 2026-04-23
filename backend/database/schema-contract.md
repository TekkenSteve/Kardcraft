# Schema Contract for API Consumers

This document is the consumer-facing schema contract for session/task control APIs.

## Canonical Control-Plane Tables

- `kc_sessions`: session ownership and summary state
- `kc_tasks`: task lifecycle and linkage to session
- `kc_events`: session timeline/event ledger
- `kc_llm_usage_ledger`: token/cost usage ledger
- `kc_card_templates`: template catalog metadata
- `kc_card_template_versions`: template version content and mapping spec
- `kc_user_template_preferences`: user-scoped default preference (legacy-compatible)
- `kc_template_default_policies`: scoped default policy source (system/user/org)

## Ownership

- Write ownership: `task-orchestrator`
- Read ownership: `task-orchestrator` APIs and frontend consumers
- Migration ownership: `backend/database/migrations` only

## Runtime Rules

1. Services must not execute schema-mutating DDL at runtime.
2. Required migration baseline: `0001_initial_schema.sql`.
3. Runtime startup checks only migration registry/version compatibility (`kc_schema_migrations`).
4. Migrations are schema-only and must not seed template content payloads.
5. CI/pipeline must enforce both guards:
   - `backend/database/scripts/check_no_template_seed.sh`
   - `backend/database/scripts/check_no_template_overwrite_in_migrations.sh`

## Legacy Table Note

Previously deprecated legacy tables (`workspaces`, `workspace_files`, `workflow_tasks`,
`document_metadata`, `vector_embeddings`, `system_metrics`, `audit_logs`) are removed
from the current unified baseline migration.
