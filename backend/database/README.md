# Database Schema Governance

This directory is the single source of truth for PostgreSQL schema changes.

## Layout

- `migrations/`: ordered SQL migration files
- `scripts/migrate.sh`: applies pending migrations and records versions in `kc_schema_migrations`

## Rules

1. Service runtime must not execute schema-mutating DDL.
2. All schema changes must be delivered via files in `migrations/`.
3. New migrations must be additive and idempotent.
4. Migrations are schema-only. Do not seed or overwrite template content data (`front_html/back_html/css/mapping_spec`) in migration SQL.
5. Template content bootstrap/import must run through dedicated bootstrap entrypoints under `backend/database/scripts/`.

## Environment Entry Semantics

- Local: `docker compose run --rm db-migrate`
- Dev/Staging/Prod: invoke the same `backend/database/scripts/migrate.sh` entrypoint before app services
- Template content bootstrap: `backend/database/scripts/bootstrap_templates.sh` (use `--force` only for explicit version overwrite)
  - `TEMPLATE_DEFAULTS_DIR` can override template manifest root path
- Bootstrap health check: `backend/database/scripts/check_template_bootstrap.sh`
- Empty-DB governance verification: `backend/database/scripts/verify_template_governance_empty_db.sh`
- One-shot cutover pipeline: `backend/database/scripts/cutover_template_governance.sh` (`--force` optional)
- Database scripts auto-fallback to `docker exec kardcraft-postgres psql` when local `psql` is unavailable.
- CI guardrails:
  - `backend/database/scripts/check_no_template_seed.sh`
  - `backend/database/scripts/check_no_template_overwrite_in_migrations.sh`
- The runtime compatibility check in `task-orchestrator` requires migration baseline `0001_initial_schema.sql` (or `KC_REQUIRED_SCHEMA_VERSION` override)
