CREATE TABLE IF NOT EXISTS agentos_runs (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT,
    node_id TEXT,
    thread_id TEXT NOT NULL DEFAULT '',
    account_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    backend_kind TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL DEFAULT '',
    external_workflow_id TEXT NOT NULL DEFAULT '',
    external_run_id TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT agentos_runs_plan_node_pair CHECK (
        (plan_id IS NULL AND node_id IS NULL)
        OR (plan_id IS NOT NULL AND node_id IS NOT NULL)
    )
);

-- GoAgent may have created its base table before Kardcraft migrations run.
-- Make this migration converge that pre-existing schema before creating indexes.
ALTER TABLE agentos_runs
    ADD COLUMN IF NOT EXISTS plan_id TEXT,
    ADD COLUMN IF NOT EXISTS node_id TEXT,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agentos_runs_thread_id
ON agentos_runs(thread_id);

CREATE INDEX IF NOT EXISTS idx_agentos_runs_backend
ON agentos_runs(backend_kind, backend_name);

CREATE INDEX IF NOT EXISTS idx_agentos_runs_lifecycle
ON agentos_runs(lifecycle_state);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agentos_runs_idempotency
ON agentos_runs(account_id, project_id, idempotency_key)
WHERE idempotency_key <> '';

CREATE INDEX IF NOT EXISTS idx_agentos_runs_plan_node
ON agentos_runs(plan_id, node_id)
WHERE plan_id IS NOT NULL;
