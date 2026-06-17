CREATE TABLE IF NOT EXISTS agentos_runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL DEFAULT '',
    account_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    backend_kind TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    external_workflow_id TEXT NOT NULL DEFAULT '',
    external_run_id TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agentos_runs_thread_id
ON agentos_runs(thread_id);

CREATE INDEX IF NOT EXISTS idx_agentos_runs_backend
ON agentos_runs(backend_kind, backend_name);

CREATE INDEX IF NOT EXISTS idx_agentos_runs_lifecycle
ON agentos_runs(lifecycle_state);
