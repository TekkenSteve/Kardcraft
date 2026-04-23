#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres123}"
PGADMIN_DB="${POSTGRES_ADMIN_DB:-postgres}"
BASE_DB="${POSTGRES_DB:-kardcraft}"
TEST_DB="${TEMPLATE_GOV_TEST_DB:-${BASE_DB}_tmplgov_${USER:-user}_$$}"
GO_BIN="${GO_BIN:-go}"
export PGPASSWORD

psql_admin() {
  if command -v psql >/dev/null 2>&1; then
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGADMIN_DB" -v ON_ERROR_STOP=1 "$@"
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "kardcraft-postgres"; then
    docker exec -i -e PGPASSWORD="$PGPASSWORD" kardcraft-postgres \
      psql -U "$PGUSER" -d "$PGADMIN_DB" -v ON_ERROR_STOP=1 "$@"
    return
  fi
  echo "[fail] psql not found and docker fallback unavailable (container: kardcraft-postgres)"
  exit 1
}

cleanup() {
  psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TEST_DB' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
  psql_admin -c "DROP DATABASE IF EXISTS \"$TEST_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "[step] recreate isolated test database: $TEST_DB"
cleanup
psql_admin -c "CREATE DATABASE \"$TEST_DB\";"

echo "[step] apply migrations on empty database"
POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$TEST_DB" \
  "$SCRIPT_DIR/migrate.sh"

echo "[step] verify bootstrap health fails before import"
if POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$TEST_DB" \
  "$SCRIPT_DIR/check_template_bootstrap.sh"; then
  echo "[fail] expected bootstrap health check to fail before template bootstrap"
  exit 1
fi

echo "[step] bootstrap templates"
POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$TEST_DB" \
  "$SCRIPT_DIR/bootstrap_templates.sh"

echo "[step] verify bootstrap health passes after import"
POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$TEST_DB" \
  "$SCRIPT_DIR/check_template_bootstrap.sh"

echo "[step] run create-task default resolution regression tests"
(
  cd "$REPO_DIR/backend/task-orchestrator"
  "$GO_BIN" test ./internal/controller/http/v1 -run 'TestHandleCreateTaskBoundaries/(main_task_without_template_and_without_resolved_default_returns_400|main_task_uses_resolved_default_template_when_missing_input_template)$' -count=1
)

echo "[ok] empty-db template governance verification passed"
