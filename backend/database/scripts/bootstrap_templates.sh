#!/bin/sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
DEFAULTS_DIR="${TEMPLATE_DEFAULTS_DIR:-$REPO_DIR/agent-workflow/src/kardcraft/card_templates/defaults}"

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-kardcraft}"
PGUSER="${POSTGRES_USER:-postgres}"
PGPASSWORD="${POSTGRES_PASSWORD:-postgres123}"
export PGPASSWORD

FORCE="0"
if [ "${1:-}" = "--force" ]; then
  FORCE="1"
fi
OPERATOR_ID="${TEMPLATE_BOOTSTRAP_OPERATOR:-system}"
SOURCE_NAME="${TEMPLATE_BOOTSTRAP_SOURCE:-backend/database/scripts/bootstrap_templates.sh}"

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

if [ ! -d "$DEFAULTS_DIR" ]; then
  echo "[fail] defaults directory not found: $DEFAULTS_DIR"
  exit 1
fi

echo "[info] bootstrap templates from $DEFAULTS_DIR (force=$FORCE)"

python3 - "$DEFAULTS_DIR" <<'PY' | while IFS= read -r payload; do
import json
import hashlib
import pathlib
import sys

base = pathlib.Path(sys.argv[1])
for manifest in sorted(base.glob("*/manifest.json")):
    root = manifest.parent
    data = json.loads(manifest.read_text(encoding="utf-8"))
    files = data.get("files") or {}

    def read_opt(name: str) -> str:
        rel = files.get(name)
        if not rel:
            return ""
        p = root / rel
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    payload = {
        "template_id": str(data.get("template_id") or "").strip(),
        "name": str(data.get("name") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "scope": str(data.get("scope") or "system").strip() or "system",
        "status": str(data.get("status") or "active").strip() or "active",
        "is_default": bool(data.get("is_default", False)),
        "version": int(data.get("version") or 1),
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        "front_html": read_opt("front_html"),
        "back_html": read_opt("back_html"),
        "css": read_opt("css"),
        "js": read_opt("js") or None,
        "mapping_spec": data.get("mapping_spec") if isinstance(data.get("mapping_spec"), dict) else {},
    }
    payload_for_digest = {
        "template_id": payload["template_id"],
        "version": payload["version"],
        "front_html": payload["front_html"],
        "back_html": payload["back_html"],
        "css": payload["css"],
        "js": payload["js"],
        "mapping_spec": payload["mapping_spec"],
    }
    payload["payload_digest"] = hashlib.sha256(
        json.dumps(payload_for_digest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if payload["template_id"] and payload["front_html"].strip() and payload["back_html"].strip():
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
PY
  if [ "$FORCE" = "1" ]; then
    run_psql -v payload="$payload" -v operator_id="$OPERATOR_ID" -v source_name="$SOURCE_NAME" <<'SQL'
WITH input AS (
  SELECT :'payload'::jsonb AS j
), template_row AS (
  INSERT INTO kc_card_templates (
    template_id, name, description, scope, owner_user_id, status, is_default, latest_version, tags, metadata, updated_at
  )
  SELECT
    j->>'template_id',
    COALESCE(NULLIF(j->>'name', ''), j->>'template_id'),
    NULLIF(j->>'description', ''),
    COALESCE(NULLIF(j->>'scope', ''), 'system'),
    NULL,
    COALESCE(NULLIF(j->>'status', ''), 'active'),
    FALSE,
    GREATEST(COALESCE((j->>'version')::int, 1), 1),
    COALESCE(j->'tags', '[]'::jsonb),
    COALESCE(j->'metadata', '{}'::jsonb),
    NOW()
  FROM input
  ON CONFLICT (template_id) DO UPDATE
  SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    latest_version = GREATEST(kc_card_templates.latest_version, EXCLUDED.latest_version),
    tags = EXCLUDED.tags,
    metadata = EXCLUDED.metadata,
    updated_at = NOW()
  RETURNING template_id
), version_row AS (
  INSERT INTO kc_card_template_versions (
    template_id, version, front_html, back_html, css, js, mapping_spec, is_published, updated_at
  )
  SELECT
    j->>'template_id',
    GREATEST(COALESCE((j->>'version')::int, 1), 1),
    COALESCE(j->>'front_html', ''),
    COALESCE(j->>'back_html', ''),
    COALESCE(j->>'css', ''),
    NULLIF(j->>'js', ''),
    COALESCE(j->'mapping_spec', '{}'::jsonb),
    TRUE,
    NOW()
  FROM input
  ON CONFLICT (template_id, version) DO UPDATE
  SET
    front_html = EXCLUDED.front_html,
    back_html = EXCLUDED.back_html,
    css = EXCLUDED.css,
    js = EXCLUDED.js,
    mapping_spec = EXCLUDED.mapping_spec,
    is_published = EXCLUDED.is_published,
    updated_at = NOW()
  RETURNING template_id
)
INSERT INTO kc_template_default_policies (
  scope_type, scope_id, default_template_id, default_template_version, updated_at
)
SELECT
  'system',
  NULL,
  j->>'template_id',
  GREATEST(COALESCE((j->>'version')::int, 1), 1),
  NOW()
FROM input
WHERE COALESCE((j->>'is_default')::boolean, FALSE) = TRUE
ON CONFLICT (scope_type) WHERE scope_type = 'system'
DO UPDATE SET
  default_template_id = EXCLUDED.default_template_id,
  default_template_version = EXCLUDED.default_template_version,
  updated_at = NOW();

WITH input AS (
  SELECT :'payload'::jsonb AS j
)
INSERT INTO kc_template_bootstrap_audit (
  template_id,
  template_version,
  operation,
  force_overwrite,
  operator_id,
  source,
  payload_digest,
  details,
  created_at
)
SELECT
  j->>'template_id',
  GREATEST(COALESCE((j->>'version')::int, 1), 1),
  'bootstrap_force_overwrite',
  TRUE,
  COALESCE(NULLIF(:'operator_id', ''), 'system'),
  COALESCE(NULLIF(:'source_name', ''), 'bootstrap_templates.sh'),
  COALESCE(NULLIF(j->>'payload_digest', ''), md5(j::text)),
  jsonb_build_object(
    'scope', COALESCE(NULLIF(j->>'scope', ''), 'system'),
    'status', COALESCE(NULLIF(j->>'status', ''), 'active')
  ),
  NOW()
FROM input;
SQL
  else
    run_psql -v payload="$payload" -v operator_id="$OPERATOR_ID" -v source_name="$SOURCE_NAME" <<'SQL'
WITH input AS (
  SELECT :'payload'::jsonb AS j
), template_row AS (
  INSERT INTO kc_card_templates (
    template_id, name, description, scope, owner_user_id, status, is_default, latest_version, tags, metadata, updated_at
  )
  SELECT
    j->>'template_id',
    COALESCE(NULLIF(j->>'name', ''), j->>'template_id'),
    NULLIF(j->>'description', ''),
    COALESCE(NULLIF(j->>'scope', ''), 'system'),
    NULL,
    COALESCE(NULLIF(j->>'status', ''), 'active'),
    FALSE,
    GREATEST(COALESCE((j->>'version')::int, 1), 1),
    COALESCE(j->'tags', '[]'::jsonb),
    COALESCE(j->'metadata', '{}'::jsonb),
    NOW()
  FROM input
  ON CONFLICT (template_id) DO NOTHING
  RETURNING template_id
), version_row AS (
  INSERT INTO kc_card_template_versions (
    template_id, version, front_html, back_html, css, js, mapping_spec, is_published, updated_at
  )
  SELECT
    j->>'template_id',
    GREATEST(COALESCE((j->>'version')::int, 1), 1),
    COALESCE(j->>'front_html', ''),
    COALESCE(j->>'back_html', ''),
    COALESCE(j->>'css', ''),
    NULLIF(j->>'js', ''),
    COALESCE(j->'mapping_spec', '{}'::jsonb),
    TRUE,
    NOW()
  FROM input
  ON CONFLICT (template_id, version) DO NOTHING
  RETURNING template_id
)
INSERT INTO kc_template_default_policies (
  scope_type, scope_id, default_template_id, default_template_version, updated_at
)
SELECT
  'system',
  NULL,
  j->>'template_id',
  GREATEST(COALESCE((j->>'version')::int, 1), 1),
  NOW()
FROM input
WHERE COALESCE((j->>'is_default')::boolean, FALSE) = TRUE
ON CONFLICT DO NOTHING;

WITH input AS (
  SELECT :'payload'::jsonb AS j
)
INSERT INTO kc_template_bootstrap_audit (
  template_id,
  template_version,
  operation,
  force_overwrite,
  operator_id,
  source,
  payload_digest,
  details,
  created_at
)
SELECT
  j->>'template_id',
  GREATEST(COALESCE((j->>'version')::int, 1), 1),
  'bootstrap_insert',
  FALSE,
  COALESCE(NULLIF(:'operator_id', ''), 'system'),
  COALESCE(NULLIF(:'source_name', ''), 'bootstrap_templates.sh'),
  COALESCE(NULLIF(j->>'payload_digest', ''), md5(j::text)),
  jsonb_build_object(
    'scope', COALESCE(NULLIF(j->>'scope', ''), 'system'),
    'status', COALESCE(NULLIF(j->>'status', ''), 'active')
  ),
  NOW()
FROM input;
SQL
  fi

done

echo "[ok] template bootstrap complete"
