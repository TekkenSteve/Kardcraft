#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATIONS_DIR="$ROOT_DIR/migrations"

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-kardcraft}"
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres123}"
export PGPASSWORD

run_psql() {
    if command -v psql >/dev/null 2>&1; then
        psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 "$@"
        return
    fi
    if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "kardcraft-postgres"; then
        docker exec -i -e PGPASSWORD="$PGPASSWORD" kardcraft-postgres \
            psql -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 "$@"
        return
    fi
    echo "[fail] psql not found and docker fallback unavailable (container: kardcraft-postgres)"
    exit 1
}

run_psql <<'SQL'
CREATE TABLE IF NOT EXISTS kc_schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

for migration in "$MIGRATIONS_DIR"/*.sql; do
    version="$(basename "$migration")"
    already_applied="$(run_psql -Atqc "SELECT 1 FROM kc_schema_migrations WHERE version = '$version' LIMIT 1;")"
    if [ "$already_applied" = "1" ]; then
        echo "[skip] $version"
        continue
    fi

    echo "[apply] $version"
    run_psql < "$migration"
    run_psql -c "INSERT INTO kc_schema_migrations(version) VALUES ('$version');"
done

echo "Migrations complete."
