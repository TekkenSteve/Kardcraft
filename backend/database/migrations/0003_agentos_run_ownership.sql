ALTER TABLE agentos_runs
    ADD COLUMN IF NOT EXISTS plan_id TEXT,
    ADD COLUMN IF NOT EXISTS node_id TEXT,
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT NOT NULL DEFAULT '';

ALTER TABLE agentos_runs
    DROP CONSTRAINT IF EXISTS agentos_runs_plan_node_pair;

ALTER TABLE agentos_runs
    ADD CONSTRAINT agentos_runs_plan_node_pair CHECK (
        (plan_id IS NULL AND node_id IS NULL)
        OR (plan_id IS NOT NULL AND node_id IS NOT NULL)
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_agentos_runs_idempotency
ON agentos_runs(account_id, project_id, idempotency_key)
WHERE idempotency_key <> '';

CREATE INDEX IF NOT EXISTS idx_agentos_runs_plan_node
ON agentos_runs(plan_id, node_id)
WHERE plan_id IS NOT NULL;
