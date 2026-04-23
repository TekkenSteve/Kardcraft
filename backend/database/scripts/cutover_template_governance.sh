#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

FORCE_FLAG=""
if [ "${1:-}" = "--force" ]; then
  FORCE_FLAG="--force"
fi

echo "[step] run schema migrations"
"$SCRIPT_DIR/migrate.sh"

echo "[step] bootstrap template content ${FORCE_FLAG:-}" 
"$SCRIPT_DIR/bootstrap_templates.sh" $FORCE_FLAG

echo "[step] verify template seed guard"
"$SCRIPT_DIR/check_no_template_seed.sh"

echo "[step] verify template overwrite guard"
"$SCRIPT_DIR/check_no_template_overwrite_in_migrations.sh"

echo "[step] verify template bootstrap health"
"$SCRIPT_DIR/check_template_bootstrap.sh"

echo "[ok] cutover pipeline complete"
