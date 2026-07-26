#!/bin/sh
set -eu

PGHOST="${POSTGRES_HOST:-postgres}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-postgres}"
PGDATABASE="${POSTGRES_DB:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres123}"
export PGPASSWORD

validate_identifier() {
    case "$2" in
        ''|*[!a-zA-Z0-9_]*)
            echo "[fail] $1 must contain only letters, numbers, and underscores" >&2
            exit 1
            ;;
    esac
}

initialize_database() {
    role_name="$1"
    role_password="$2"
    database_name="$3"

    validate_identifier "database role" "$role_name"
    validate_identifier "database name" "$database_name"

    psql \
        -h "$PGHOST" \
        -p "$PGPORT" \
        -U "$PGUSER" \
        -d "$PGDATABASE" \
        -v ON_ERROR_STOP=1 \
        -v role_name="$role_name" \
        -v role_password="$role_password" \
        -v database_name="$database_name" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'role_name')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role_name') \gexec

SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L',
    :'role_name',
    :'role_password'
) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'database_name', :'role_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'database_name') \gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', :'database_name', :'role_name') \gexec
SQL

    # Reconcile objects created by the previous shared-admin configuration.
    # New installations have no objects yet; on upgrades this transfers only
    # objects in the auth database's public schema, never objects in other DBs.
    psql \
        -h "$PGHOST" \
        -p "$PGPORT" \
        -U "$PGUSER" \
        -d "$database_name" \
        -v ON_ERROR_STOP=1 \
        -v role_name="$role_name" <<'SQL'
SELECT format('ALTER SCHEMA public OWNER TO %I', :'role_name') \gexec

SELECT format(
    'ALTER %s %I.%I OWNER TO %I',
    CASE c.relkind
        WHEN 'S' THEN 'SEQUENCE'
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        WHEN 'f' THEN 'FOREIGN TABLE'
        ELSE 'TABLE'
    END,
    n.nspname,
    c.relname,
    :'role_name'
)
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
  AND (
      c.relkind <> 'S'
      OR NOT EXISTS (
          SELECT 1
          FROM pg_depend AS d
          WHERE d.classid = 'pg_class'::regclass
            AND d.objid = c.oid
            AND d.deptype IN ('a', 'i')
      )
  ) \gexec
SQL

    echo "[ok] database $database_name is owned by role $role_name"
}

initialize_database \
    "${KRATOS_DB_USER:-kratos}" \
    "${KRATOS_DB_PASSWORD:-kratos}" \
    "${KRATOS_DB_NAME:-kratos}"

initialize_database \
    "${HYDRA_DB_USER:-hydra}" \
    "${HYDRA_DB_PASSWORD:-hydra}" \
    "${HYDRA_DB_NAME:-hydra}"

initialize_database \
    "${AGENTOS_DB_USER:-agentos}" \
    "${AGENTOS_DB_PASSWORD:-agentos}" \
    "${AGENTOS_DB_NAME:-agentos}"
