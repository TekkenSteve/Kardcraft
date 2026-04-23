#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATIONS_DIR="$ROOT_DIR/migrations"

# Guardrail: migration files are schema-only and must not seed template content.
if rg -n -i "insert\s+into\s+kc_card_templates|insert\s+into\s+kc_card_template_versions" "$MIGRATIONS_DIR" >/dev/null 2>&1; then
  echo "[fail] template seed statements detected in migration files"
  echo "       move template content bootstrap to dedicated scripts, not migrations"
  rg -n -i "insert\s+into\s+kc_card_templates|insert\s+into\s+kc_card_template_versions" "$MIGRATIONS_DIR"
  exit 1
fi

echo "[ok] no template seed statements found in migrations"
