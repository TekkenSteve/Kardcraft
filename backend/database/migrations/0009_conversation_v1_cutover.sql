-- The agentos.conversation.v1 switch intentionally does not resume legacy
-- Temporal histories. Preserve their business rows, but make them terminal so
-- new projectors and dispatchers only operate on post-cutover runs.
UPDATE kc_tasks
SET status = 'cancelled',
    error_message = COALESCE(NULLIF(error_message, ''), 'Cancelled by agentos.conversation.v1 cutover'),
    completed_at = COALESCE(completed_at, NOW()),
    updated_at = NOW()
WHERE LOWER(COALESCE(status, '')) IN ('pending', 'queued', 'running', 'paused');

UPDATE kc_sessions
SET latest_task_status = 'cancelled',
    updated_at = NOW()
WHERE LOWER(COALESCE(latest_task_status, '')) IN ('pending', 'queued', 'running', 'paused');
