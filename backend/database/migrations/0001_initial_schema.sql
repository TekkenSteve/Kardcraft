-- ============================================================================
-- Kardcraft unified baseline schema (first-run only)
-- ============================================================================
--
-- Governance rules:
-- 1) Migration is schema-only. No template content seed in migration SQL.
-- 2) Template content must be imported via backend/database/scripts/bootstrap_templates.sh.
-- ============================================================================

SET search_path TO public;

-- ============================================================================
-- Core session/task control plane
-- ============================================================================

CREATE TABLE IF NOT EXISTS kc_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    title VARCHAR(255),
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    task_count INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ,
    latest_task_query TEXT,
    latest_task_status VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_kc_sessions_user_id ON kc_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_kc_sessions_updated_at ON kc_sessions (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_sessions_created_at ON kc_sessions (created_at DESC);

CREATE TABLE IF NOT EXISTS kc_tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(64) REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    query TEXT,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_kc_tasks_user_id ON kc_tasks (user_id);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_session_id ON kc_tasks (session_id);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_status ON kc_tasks (status);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_created_at ON kc_tasks (created_at DESC);

CREATE TABLE IF NOT EXISTS kc_llm_usage_ledger (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    schema_version VARCHAR(32) NOT NULL DEFAULT '1',
    task_id VARCHAR(128) NOT NULL REFERENCES kc_tasks(task_id) ON DELETE CASCADE,
    workflow_id VARCHAR(128),
    session_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    intent VARCHAR(64),
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(255) NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    input_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    output_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    cache_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    total_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    estimated BOOLEAN NOT NULL DEFAULT FALSE,
    source VARCHAR(32) NOT NULL DEFAULT 'exact',
    external_request_id VARCHAR(160),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_llm_usage_ledger_non_negative_tokens CHECK (
        prompt_tokens >= 0 AND
        completion_tokens >= 0 AND
        cache_read_tokens >= 0 AND
        cache_write_tokens >= 0 AND
        total_tokens >= 0
    ),
    CONSTRAINT ck_kc_llm_usage_ledger_non_negative_costs CHECK (
        input_cost_usd >= 0 AND
        output_cost_usd >= 0 AND
        cache_cost_usd >= 0 AND
        total_cost_usd >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_task_id ON kc_llm_usage_ledger (task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_session_id ON kc_llm_usage_ledger (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_user_id ON kc_llm_usage_ledger (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_model_provider ON kc_llm_usage_ledger (model, provider, created_at DESC);

CREATE TABLE IF NOT EXISTS kc_events (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    task_id VARCHAR(128),
    workflow_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL,
    message TEXT,
    payload JSONB,
    stream_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kc_events_session_id ON kc_events (session_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_task_id ON kc_events (task_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_workflow_id ON kc_events (workflow_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_created_at ON kc_events (created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_events_workflow_stream
    ON kc_events (workflow_id, stream_id)
    WHERE stream_id IS NOT NULL;

-- ============================================================================
-- Card storage domain tables
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cardmodel') THEN
        CREATE TYPE cardmodel AS ENUM ('Basic', 'Cloze', 'IR', 'Reverse');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'editstatus') THEN
        CREATE TYPE editstatus AS ENUM ('draft', 'ai_editing', 'user_editing', 'confirmed');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS cards (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    card_id VARCHAR(64) NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    model cardmodel NOT NULL DEFAULT 'Basic',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    media JSONB NOT NULL DEFAULT '[]'::jsonb,
    edit_status editstatus NOT NULL DEFAULT 'draft',
    locked_by VARCHAR(128),
    locked_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE,
    manual_edits INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_card_version_positive CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_cards_user_modified ON cards (user_id, modified_at);
CREATE INDEX IF NOT EXISTS idx_cards_edit_status ON cards (edit_status, locked_at);
CREATE INDEX IF NOT EXISTS idx_cards_concepts ON cards USING gin (concepts);

CREATE TABLE IF NOT EXISTS card_versions (
    id UUID PRIMARY KEY,
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    diff JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_snapshot JSONB,
    changed_by VARCHAR(128) NOT NULL,
    change_comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_card_version UNIQUE (card_id, version)
);

CREATE INDEX IF NOT EXISTS idx_card_versions_card_version ON card_versions (card_id, version);

CREATE TABLE IF NOT EXISTS packs (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    pack_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_packs_user_id ON packs (user_id);

CREATE TABLE IF NOT EXISTS pack_cards (
    id UUID PRIMARY KEY,
    pack_id UUID NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    added_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pack_card UNIQUE (pack_id, card_id)
);

CREATE INDEX IF NOT EXISTS idx_pack_cards_pack_id ON pack_cards (pack_id);
CREATE INDEX IF NOT EXISTS idx_pack_cards_card_id ON pack_cards (card_id);

CREATE TABLE IF NOT EXISTS media (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    media_id VARCHAR(64) NOT NULL UNIQUE,
    file_name VARCHAR(512) NOT NULL,
    file_type VARCHAR(64) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    file_size INTEGER,
    mime_type VARCHAR(128),
    file_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_media_user_id ON media (user_id);

-- ============================================================================
-- Template governance schema (structure only)
-- ============================================================================

CREATE TABLE IF NOT EXISTS kc_card_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    scope VARCHAR(32) NOT NULL DEFAULT 'system',
    owner_user_id VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
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
    css TEXT NOT NULL,
    js TEXT,
    mapping_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_id, version),
    CONSTRAINT ck_kc_card_template_versions_version CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_kc_card_template_versions_template_published
    ON kc_card_template_versions (template_id, is_published, version DESC);

CREATE TABLE IF NOT EXISTS kc_user_template_preferences (
    user_id VARCHAR(255) PRIMARY KEY,
    default_template_id VARCHAR(128) NOT NULL REFERENCES kc_card_templates(template_id) ON DELETE CASCADE,
    default_template_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_user_template_preferences_version CHECK (default_template_version >= 1),
    CONSTRAINT fk_kc_user_template_preferences_template_version
        FOREIGN KEY (default_template_id, default_template_version)
        REFERENCES kc_card_template_versions (template_id, version)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kc_template_default_policies (
    id BIGSERIAL PRIMARY KEY,
    scope_type VARCHAR(16) NOT NULL,
    scope_id VARCHAR(255),
    default_template_id VARCHAR(128) NOT NULL,
    default_template_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_template_default_policies_scope_type
        CHECK (scope_type IN ('system', 'user', 'org')),
    CONSTRAINT ck_kc_template_default_policies_scope_id
        CHECK (
            (scope_type = 'system' AND scope_id IS NULL) OR
            (scope_type IN ('user', 'org') AND scope_id IS NOT NULL)
        ),
    CONSTRAINT ck_kc_template_default_policies_version
        CHECK (default_template_version >= 1),
    CONSTRAINT fk_kc_template_default_policies_template_version
        FOREIGN KEY (default_template_id, default_template_version)
        REFERENCES kc_card_template_versions (template_id, version)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kc_template_default_policies_system
    ON kc_template_default_policies (scope_type)
    WHERE scope_type = 'system';

CREATE UNIQUE INDEX IF NOT EXISTS idx_kc_template_default_policies_user
    ON kc_template_default_policies (scope_type, scope_id)
    WHERE scope_type = 'user';

CREATE UNIQUE INDEX IF NOT EXISTS idx_kc_template_default_policies_org
    ON kc_template_default_policies (scope_type, scope_id)
    WHERE scope_type = 'org';

CREATE TABLE IF NOT EXISTS kc_template_bootstrap_audit (
    id BIGSERIAL PRIMARY KEY,
    template_id VARCHAR(128) NOT NULL,
    template_version INTEGER NOT NULL,
    operation VARCHAR(32) NOT NULL,
    force_overwrite BOOLEAN NOT NULL DEFAULT FALSE,
    operator_id VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    payload_digest VARCHAR(128),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_template_bootstrap_audit_version CHECK (template_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_kc_template_bootstrap_audit_template
    ON kc_template_bootstrap_audit (template_id, template_version, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_template_bootstrap_audit_operator
    ON kc_template_bootstrap_audit (operator_id, created_at DESC);

-- ============================================================================
-- Common trigger helpers
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_modified_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_kc_sessions_updated_at ON kc_sessions;
CREATE TRIGGER update_kc_sessions_updated_at BEFORE UPDATE ON kc_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_kc_tasks_updated_at ON kc_tasks;
CREATE TRIGGER update_kc_tasks_updated_at BEFORE UPDATE ON kc_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_kc_card_templates_updated_at ON kc_card_templates;
CREATE TRIGGER update_kc_card_templates_updated_at BEFORE UPDATE ON kc_card_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_kc_card_template_versions_updated_at ON kc_card_template_versions;
CREATE TRIGGER update_kc_card_template_versions_updated_at BEFORE UPDATE ON kc_card_template_versions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_kc_user_template_preferences_updated_at ON kc_user_template_preferences;
CREATE TRIGGER update_kc_user_template_preferences_updated_at BEFORE UPDATE ON kc_user_template_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_kc_template_default_policies_updated_at ON kc_template_default_policies;
CREATE TRIGGER update_kc_template_default_policies_updated_at BEFORE UPDATE ON kc_template_default_policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_cards_modified_at ON cards;
CREATE TRIGGER update_cards_modified_at BEFORE UPDATE ON cards
    FOR EACH ROW EXECUTE FUNCTION update_modified_at_column();

DO $$
BEGIN
    RAISE NOTICE 'Kardcraft unified baseline schema initialized.';
END $$;
