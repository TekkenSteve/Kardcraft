#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATIONS_DIR="$ROOT_DIR/migrations"

# Guardrail: migrations must not mutate template content rows via upsert-update.
matches="$(
  perl -0ne '
    if (/insert\s+into\s+kc_card_template_versions.*?on\s+conflict\s*\(\s*template_id\s*,\s*version\s*\)\s*do\s+update/is) {
      print "$ARGV\n";
    }
  ' "$MIGRATIONS_DIR"/*.sql
)"

if [ -n "$matches" ]; then
  echo "[fail] template version overwrite upsert detected in migration files"
  echo "       migration must remain schema-only for template content"
  printf "%s\n" "$matches"
  exit 1
fi

echo "[ok] no template overwrite upsert statements found in migrations"
