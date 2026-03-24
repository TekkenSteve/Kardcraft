# Database Schema Governance

This directory is the single source of truth for PostgreSQL schema changes.

## Layout

- `migrations/`: ordered SQL migration files
- `scripts/migrate.sh`: applies pending migrations and records versions in `kc_schema_migrations`

## Rules

1. Service runtime must not execute schema-mutating DDL.
2. All schema changes must be delivered via files in `migrations/`.
3. New migrations must be additive and idempotent.

## Environment Entry Semantics

- Local: `docker compose run --rm db-migrate`
- Dev/Staging/Prod: invoke the same `backend/database/scripts/migrate.sh` entrypoint before app services
- The runtime compatibility check in `task-orchestrator` requires migration baseline `0001_initial_schema.sql` (or `KC_REQUIRED_SCHEMA_VERSION` override)
