CREATE TABLE IF NOT EXISTS kc_schedules (
    schedule_id VARCHAR(128) PRIMARY KEY,
    temporal_schedule_id VARCHAR(160) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    cron_expression VARCHAR(255) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    task_query TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_schedules_status CHECK (status IN ('active', 'paused'))
);

CREATE INDEX IF NOT EXISTS idx_kc_schedules_user_updated
    ON kc_schedules (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS kc_schedule_runs (
    schedule_run_id BIGSERIAL PRIMARY KEY,
    schedule_id VARCHAR(128) NOT NULL REFERENCES kc_schedules(schedule_id) ON DELETE CASCADE,
    task_id VARCHAR(128) NOT NULL UNIQUE,
    session_id VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'dispatching',
    error_message TEXT,
    triggered_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kc_schedule_runs_schedule_triggered
    ON kc_schedule_runs (schedule_id, triggered_at DESC);

ALTER TABLE kc_card_template_versions
    ADD COLUMN IF NOT EXISTS assets_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS compatibility JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS changelog TEXT;

DROP TRIGGER IF EXISTS update_kc_schedules_updated_at ON kc_schedules;
CREATE TRIGGER update_kc_schedules_updated_at BEFORE UPDATE ON kc_schedules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
