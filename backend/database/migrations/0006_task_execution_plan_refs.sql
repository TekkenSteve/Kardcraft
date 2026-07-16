-- The former AgentOS run path cannot resume through PlanRuntime. Refuse an
-- upgrade while it still owns live work instead of silently splitting a task
-- between two execution control planes.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM kc_tasks
        WHERE LOWER(COALESCE(status, '')) IN ('pending', 'queued', 'running', 'paused')
    ) THEN
        RAISE EXCEPTION 'cannot install PlanRuntime task execution while legacy tasks are unfinished';
    END IF;
END $$;

CREATE TABLE kc_task_execution (
    task_id VARCHAR(128) PRIMARY KEY REFERENCES kc_tasks(task_id) ON DELETE CASCADE,
    plan_id VARCHAR(128) NOT NULL UNIQUE,
    account_id VARCHAR(255) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    node_id VARCHAR(128) NOT NULL,
    backend_run_id VARCHAR(128) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_task_execution_identity CHECK (
        task_id <> '' AND plan_id <> '' AND account_id <> '' AND project_id <> '' AND node_id <> '' AND backend_run_id <> ''
    )
);

CREATE INDEX idx_kc_task_execution_plan_scope
    ON kc_task_execution (plan_id, account_id, project_id);
