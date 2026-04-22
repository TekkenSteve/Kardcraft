-- Card template catalog tables used by task-orchestrator and agent-workflow.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS kc_card_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    scope VARCHAR(16) NOT NULL DEFAULT 'system',
    owner_user_id VARCHAR(255),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    latest_version INTEGER NOT NULL DEFAULT 1,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_card_templates_scope CHECK (scope IN ('system', 'user', 'org')),
    CONSTRAINT ck_kc_card_templates_status CHECK (status IN ('active', 'archived', 'disabled')),
    CONSTRAINT ck_kc_card_templates_latest_version CHECK (latest_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_kc_card_templates_scope_status
    ON kc_card_templates (scope, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_card_templates_owner_status
    ON kc_card_templates (owner_user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS kc_card_template_versions (
    template_id VARCHAR(128) NOT NULL REFERENCES kc_card_templates(template_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    front_html TEXT NOT NULL,
    back_html TEXT NOT NULL,
    css TEXT NOT NULL DEFAULT '',
    js TEXT,
    assets_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    mapping_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    compatibility JSONB NOT NULL DEFAULT '{}'::jsonb,
    changelog TEXT,
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_id, version),
    CONSTRAINT ck_kc_card_template_versions_version CHECK (version >= 1)
);

-- Backfill columns for pre-existing tables created by older schemas.
-- CREATE TABLE IF NOT EXISTS does not modify existing table definitions.
ALTER TABLE kc_card_templates
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE kc_card_template_versions
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_kc_card_template_versions_template_published
    ON kc_card_template_versions (template_id, is_published, version DESC);

CREATE TABLE IF NOT EXISTS kc_user_template_preferences (
    user_id VARCHAR(255) PRIMARY KEY,
    default_template_id VARCHAR(128) NOT NULL REFERENCES kc_card_templates(template_id) ON DELETE CASCADE,
    default_template_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_user_template_preferences_version CHECK (default_template_version >= 1)
);

-- Seed default system template required by template list/export flows.
INSERT INTO kc_card_templates (
    template_id,
    name,
    description,
    scope,
    owner_user_id,
    status,
    is_default,
    latest_version,
    tags,
    metadata
)
VALUES (
    'anki-quizify',
    'Anki Quizify',
    'Default interactive Anki template',
    'system',
    NULL,
    'active',
    TRUE,
    1,
    '["anki","default","quizify"]'::jsonb,
    '{"source":"kardcraft/card_templates/defaults/anki-quizify","license":"MIT"}'::jsonb
)
ON CONFLICT (template_id) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    is_default = EXCLUDED.is_default,
    latest_version = GREATEST(kc_card_templates.latest_version, EXCLUDED.latest_version),
    tags = EXCLUDED.tags,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO kc_card_template_versions (
    template_id,
    version,
    front_html,
    back_html,
    css,
    js,
    mapping_spec,
    is_published
)
VALUES (
    'anki-quizify',
    1,
    '<div class="quizify-card"><div class="deck">{{Deck}}</div><div class="front">{{Front}}</div>{{#Tags}}<div class="tags">{{clickable:Tags}}</div>{{/Tags}}</div>',
    '<div class="quizify-card"><div class="deck">{{Deck}}</div><div class="front">{{Front}}</div>{{#Back}}<hr/><div class="back">{{Back}}</div>{{/Back}}{{#Tags}}<div class="tags">{{clickable:Tags}}</div>{{/Tags}}</div>',
    '.quizify-card{font-family:Arial,sans-serif;line-height:1.6}.deck{font-size:12px;opacity:.75;margin-bottom:8px}.front,.back{font-size:18px}.tags{margin-top:10px;font-size:12px;opacity:.8}',
    NULL,
    '{
      "default_profile":"mcq",
      "profiles":[
        {
          "name":"mcq",
          "sample_fields":{
            "Deck":"Kardcraft::Default",
            "Front":"What is active recall?",
            "Back":"Retrieving information from memory.",
            "Tags":"kardcraft::default::mcq"
          }
        },
        {
          "name":"cloze",
          "sample_fields":{
            "Deck":"Kardcraft::Default",
            "Front":"Spaced repetition improves {{long-term memory}}.",
            "Back":"Review at expanding intervals.",
            "Tags":"kardcraft::default::cloze"
          }
        }
      ]
    }'::jsonb,
    TRUE
)
ON CONFLICT (template_id, version) DO UPDATE
SET
    front_html = EXCLUDED.front_html,
    back_html = EXCLUDED.back_html,
    css = EXCLUDED.css,
    js = EXCLUDED.js,
    mapping_spec = EXCLUDED.mapping_spec,
    is_published = EXCLUDED.is_published,
    updated_at = NOW();
