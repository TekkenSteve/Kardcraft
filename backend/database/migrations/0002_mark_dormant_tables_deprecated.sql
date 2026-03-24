-- Mark dormant legacy tables as deprecated in schema metadata.
-- This migration is intentionally non-destructive.

COMMENT ON TABLE workspaces IS '[DEPRECATED] Legacy workspace table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE workspace_files IS '[DEPRECATED] Legacy workspace files table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE workflow_tasks IS '[DEPRECATED] Legacy workflow task table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE document_metadata IS '[DEPRECATED] Legacy document metadata table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE vector_embeddings IS '[DEPRECATED] Legacy vector embedding table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE system_metrics IS '[DEPRECATED] Legacy metrics table. Do not add new writes. Planned drop after observation window.';
COMMENT ON TABLE audit_logs IS '[DEPRECATED] Legacy audit table. Do not add new writes. Planned drop after observation window.';
