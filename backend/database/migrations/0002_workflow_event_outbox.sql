CREATE TABLE IF NOT EXISTS workflow_event_outbox (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,
    workflow_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_seq BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'timeline',
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'pending',
    projector_id TEXT,
    claimed_at TIMESTAMPTZ,
    projected_at TIMESTAMPTZ,
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    CONSTRAINT uq_outbox_task_seq UNIQUE (task_id, event_seq),
    CONSTRAINT ck_outbox_status CHECK (status in ('pending', 'projecting', 'projected'))
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
ON workflow_event_outbox(status, id);

CREATE INDEX IF NOT EXISTS idx_outbox_task_seq
ON workflow_event_outbox(task_id, event_seq);

CREATE TABLE IF NOT EXISTS task_lifecycle_state (
    task_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    accepting_progress BOOLEAN NOT NULL DEFAULT TRUE,
    accepting_usage BOOLEAN NOT NULL DEFAULT TRUE,
    terminal_event_emitted BOOLEAN NOT NULL DEFAULT FALSE,
    done_event_emitted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_task_lifecycle_phase
    CHECK (phase in ('running', 'paused', 'cancelling', 'terminal'))
);

CREATE TABLE IF NOT EXISTS task_event_seq (
    task_id TEXT PRIMARY KEY,
    next_seq BIGINT NOT NULL
);
