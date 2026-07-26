CREATE TABLE IF NOT EXISTS kc_conversation_dispatch_outbox (
    dispatch_id UUID PRIMARY KEY,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    thread_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    run_id VARCHAR(128) NOT NULL UNIQUE,
    process_id VARCHAR(128) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    dispatch_kind VARCHAR(16) NOT NULL CHECK (dispatch_kind IN ('start', 'resume')),
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'dispatching', 'dispatched', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dispatched_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_kc_conversation_dispatch_due
    ON kc_conversation_dispatch_outbox (next_attempt_at, created_at)
    WHERE status IN ('pending', 'dispatching');
