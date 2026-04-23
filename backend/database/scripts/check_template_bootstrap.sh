#!/bin/sh
set -eu

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-kardcraft}"
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres123}"
export PGPASSWORD

run_psql() {
  if command -v psql >/dev/null 2>&1; then
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -At -v ON_ERROR_STOP=1 "$@"
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "kardcraft-postgres"; then
    docker exec -i -e PGPASSWORD="$PGPASSWORD" kardcraft-postgres \
      psql -U "$PGUSER" -d "$PGDATABASE" -At -v ON_ERROR_STOP=1 "$@"
    return
  fi
  echo "[fail] psql not found and docker fallback unavailable (container: kardcraft-postgres)"
  exit 1
}

templates_count="$(run_psql -c "SELECT COUNT(*) FROM kc_card_templates WHERE status = 'active';")"
versions_count="$(run_psql -c "SELECT COUNT(*) FROM kc_card_template_versions;")"
policies_count="$(run_psql -c "SELECT COUNT(*) FROM kc_template_default_policies WHERE scope_type = 'system';")"

if [ "$templates_count" -le 0 ] || [ "$versions_count" -le 0 ]; then
  echo "[fail] template bootstrap missing: active templates=$templates_count versions=$versions_count"
  echo "       run: backend/database/scripts/bootstrap_templates.sh"
  exit 1
fi

if [ "$policies_count" -le 0 ]; then
  echo "[warn] no system default policy found in kc_template_default_policies"
  echo "       task creation may require explicit template_id"
fi

echo "[ok] template bootstrap ready: active templates=$templates_count versions=$versions_count system_policies=$policies_count"
