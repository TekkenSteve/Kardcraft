-- Drop dormant legacy tables after deprecation/audit gate.

DROP VIEW IF EXISTS workflow_stats;
DROP VIEW IF EXISTS user_activity_stats;

DROP TRIGGER IF EXISTS update_workspace_files_updated_at ON workspace_files;
DROP TRIGGER IF EXISTS update_workspaces_updated_at ON workspaces;
DROP TRIGGER IF EXISTS update_workflow_tasks_updated_at ON workflow_tasks;

DROP TABLE IF EXISTS workspace_files;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS workflow_tasks;
DROP TABLE IF EXISTS document_metadata;
DROP TABLE IF EXISTS vector_embeddings;
DROP TABLE IF EXISTS system_metrics;
DROP TABLE IF EXISTS audit_logs;
