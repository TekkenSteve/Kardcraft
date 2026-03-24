-- ============================================================================
-- Kardcraft 数据库初始化脚本
-- ============================================================================

-- 设置搜索路径
SET search_path TO public;

-- ============================================================================
-- 创建工作空间表
-- ============================================================================

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    storage_path VARCHAR(1024) NOT NULL,
    minio_bucket VARCHAR(255) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(user_id)
);

COMMENT ON TABLE workspaces IS '用户工作空间表';
COMMENT ON COLUMN workspaces.workspace_id IS '工作空间ID';
COMMENT ON COLUMN workspaces.user_id IS '用户ID';
COMMENT ON COLUMN workspaces.storage_path IS '存储路径';
COMMENT ON COLUMN workspaces.minio_bucket IS 'MinIO桶名称';
COMMENT ON COLUMN workspaces.metadata IS '元数据（JSON格式）';
COMMENT ON COLUMN workspaces.created_at IS '创建时间';
COMMENT ON COLUMN workspaces.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS idx_workspaces_user_id ON workspaces (user_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_created_at ON workspaces (created_at DESC);

-- ============================================================================
-- 创建工作空间文件表
-- ============================================================================

CREATE TABLE IF NOT EXISTS workspace_files (
    file_id VARCHAR(36) PRIMARY KEY,
    workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    filename VARCHAR(512) NOT NULL,
    filepath VARCHAR(1024) NOT NULL,
    size BIGINT NOT NULL,
    mime_type VARCHAR(255),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE workspace_files IS '工作空间文件表';
COMMENT ON COLUMN workspace_files.file_id IS '文件ID';
COMMENT ON COLUMN workspace_files.workspace_id IS '工作空间ID';
COMMENT ON COLUMN workspace_files.filename IS '文件名';
COMMENT ON COLUMN workspace_files.filepath IS '文件路径';
COMMENT ON COLUMN workspace_files.size IS '文件大小（字节）';
COMMENT ON COLUMN workspace_files.mime_type IS 'MIME类型';
COMMENT ON COLUMN workspace_files.metadata IS '元数据（JSON格式）';
COMMENT ON COLUMN workspace_files.created_at IS '创建时间';
COMMENT ON COLUMN workspace_files.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS idx_workspace_files_workspace_id ON workspace_files (workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_files_filename ON workspace_files (filename);
CREATE INDEX IF NOT EXISTS idx_workspace_files_created_at ON workspace_files (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workspace_files_mime_type ON workspace_files (mime_type);

-- ============================================================================
-- 创建工作流任务表
-- ============================================================================

CREATE TABLE IF NOT EXISTS workflow_tasks (
    task_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    workflow_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress FLOAT DEFAULT 0.0,
    input_data JSONB DEFAULT '{}'::jsonb,
    result_data JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    checkpoint_id VARCHAR(255),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE workflow_tasks IS '工作流任务表';
COMMENT ON COLUMN workflow_tasks.task_id IS '任务ID';
COMMENT ON COLUMN workflow_tasks.user_id IS '用户ID';
COMMENT ON COLUMN workflow_tasks.workflow_type IS '工作流类型';
COMMENT ON COLUMN workflow_tasks.status IS '状态（pending, running, completed, failed, cancelled）';
COMMENT ON COLUMN workflow_tasks.progress IS '进度（0.0-1.0）';
COMMENT ON COLUMN workflow_tasks.input_data IS '输入数据（JSON格式）';
COMMENT ON COLUMN workflow_tasks.result_data IS '结果数据（JSON格式）';
COMMENT ON COLUMN workflow_tasks.error_message IS '错误信息';
COMMENT ON COLUMN workflow_tasks.checkpoint_id IS '检查点ID';
COMMENT ON COLUMN workflow_tasks.metadata IS '元数据（JSON格式）';
COMMENT ON COLUMN workflow_tasks.created_at IS '创建时间';
COMMENT ON COLUMN workflow_tasks.updated_at IS '更新时间';
COMMENT ON COLUMN workflow_tasks.completed_at IS '完成时间';

CREATE INDEX IF NOT EXISTS idx_workflow_tasks_user_id ON workflow_tasks (user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_status ON workflow_tasks (status);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_workflow_type ON workflow_tasks (workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_created_at ON workflow_tasks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_checkpoint_id ON workflow_tasks (checkpoint_id);

-- ============================================================================
-- 创建会话与任务元数据表（用于 Sessions API）
-- ============================================================================

CREATE TABLE IF NOT EXISTS kc_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    title VARCHAR(255),
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    task_count INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMP WITH TIME ZONE,
    latest_task_query TEXT,
    latest_task_status VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_kc_sessions_user_id ON kc_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_kc_sessions_updated_at ON kc_sessions (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_sessions_created_at ON kc_sessions (created_at DESC);

CREATE TABLE IF NOT EXISTS kc_tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(64) REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    query TEXT,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_kc_tasks_user_id ON kc_tasks (user_id);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_session_id ON kc_tasks (session_id);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_status ON kc_tasks (status);
CREATE INDEX IF NOT EXISTS idx_kc_tasks_created_at ON kc_tasks (created_at DESC);

-- ============================================================================
-- LLM 调用用量账本（审计与聚合真相源）
-- ============================================================================

CREATE TABLE IF NOT EXISTS kc_llm_usage_ledger (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
    schema_version VARCHAR(32) NOT NULL DEFAULT '1',
    task_id VARCHAR(128) NOT NULL REFERENCES kc_tasks(task_id) ON DELETE CASCADE,
    workflow_id VARCHAR(128),
    session_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    intent VARCHAR(64),
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(255) NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    input_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    output_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    cache_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    total_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    estimated BOOLEAN NOT NULL DEFAULT FALSE,
    source VARCHAR(32) NOT NULL DEFAULT 'exact',
    external_request_id VARCHAR(160),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kc_llm_usage_ledger_non_negative_tokens CHECK (
        prompt_tokens >= 0 AND
        completion_tokens >= 0 AND
        cache_read_tokens >= 0 AND
        cache_write_tokens >= 0 AND
        total_tokens >= 0
    ),
    CONSTRAINT ck_kc_llm_usage_ledger_non_negative_costs CHECK (
        input_cost_usd >= 0 AND
        output_cost_usd >= 0 AND
        cache_cost_usd >= 0 AND
        total_cost_usd >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_task_id ON kc_llm_usage_ledger (task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_session_id ON kc_llm_usage_ledger (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_user_id ON kc_llm_usage_ledger (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kc_llm_usage_ledger_model_provider ON kc_llm_usage_ledger (model, provider, created_at DESC);

-- ============================================================================
-- 事件表（用于 Sessions Events API）
-- ============================================================================

CREATE TABLE IF NOT EXISTS kc_events (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    task_id VARCHAR(128),
    workflow_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL,
    message TEXT,
    payload JSONB,
    stream_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kc_events_session_id ON kc_events (session_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_task_id ON kc_events (task_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_workflow_id ON kc_events (workflow_id);
CREATE INDEX IF NOT EXISTS idx_kc_events_created_at ON kc_events (created_at);
-- Existing deployments may contain duplicated stream_id rows caused by earlier
-- non-atomic event ingestion. Keep the newest row before enforcing uniqueness.
WITH duplicated AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY workflow_id, stream_id
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM kc_events
    WHERE stream_id IS NOT NULL
      AND workflow_id IS NOT NULL
)
DELETE FROM kc_events e
USING duplicated d
WHERE e.id = d.id
  AND d.rn > 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_events_workflow_stream
    ON kc_events (workflow_id, stream_id)
    WHERE stream_id IS NOT NULL;

-- ============================================================================
-- 创建卡片相关表（对齐 SQLAlchemy models）
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cardmodel') THEN
        CREATE TYPE cardmodel AS ENUM ('Basic', 'Cloze', 'IR', 'Reverse');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'editstatus') THEN
        CREATE TYPE editstatus AS ENUM ('draft', 'ai_editing', 'user_editing', 'confirmed');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS cards (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    card_id VARCHAR(64) NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    model cardmodel NOT NULL DEFAULT 'Basic',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    media JSONB NOT NULL DEFAULT '[]'::jsonb,
    edit_status editstatus NOT NULL DEFAULT 'draft',
    locked_by VARCHAR(128),
    locked_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE,
    manual_edits INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT ck_card_version_positive CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_cards_user_modified ON cards (user_id, modified_at);
CREATE INDEX IF NOT EXISTS idx_cards_edit_status ON cards (edit_status, locked_at);
CREATE INDEX IF NOT EXISTS idx_cards_concepts ON cards USING gin (concepts);

COMMENT ON TABLE cards IS '卡片表';
COMMENT ON COLUMN cards.card_id IS '卡片ID';
COMMENT ON COLUMN cards.user_id IS '用户ID';
COMMENT ON COLUMN cards.data IS '卡片内容（JSON）';
COMMENT ON COLUMN cards.model IS '卡片模型';
COMMENT ON COLUMN cards.edit_status IS '编辑状态';
COMMENT ON COLUMN cards.concepts IS '概念标签';
COMMENT ON COLUMN cards.created_at IS '创建时间';
COMMENT ON COLUMN cards.modified_at IS '更新时间';

CREATE TABLE IF NOT EXISTS card_versions (
    id UUID PRIMARY KEY,
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    diff JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_snapshot JSONB,
    changed_by VARCHAR(128) NOT NULL,
    change_comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_card_version UNIQUE (card_id, version)
);

CREATE INDEX IF NOT EXISTS idx_card_versions_card_version ON card_versions (card_id, version);

CREATE TABLE IF NOT EXISTS packs (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    pack_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_packs_user_id ON packs (user_id);

CREATE TABLE IF NOT EXISTS pack_cards (
    id UUID PRIMARY KEY,
    pack_id UUID NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    added_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pack_card UNIQUE (pack_id, card_id)
);

CREATE INDEX IF NOT EXISTS idx_pack_cards_pack_id ON pack_cards (pack_id);
CREATE INDEX IF NOT EXISTS idx_pack_cards_card_id ON pack_cards (card_id);

CREATE TABLE IF NOT EXISTS media (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    media_id VARCHAR(64) NOT NULL UNIQUE,
    file_name VARCHAR(512) NOT NULL,
    file_type VARCHAR(64) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    file_size INTEGER,
    mime_type VARCHAR(128),
    file_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_media_user_id ON media (user_id);

-- ============================================================================
-- 创建文档元数据表
-- ============================================================================

CREATE TABLE IF NOT EXISTS document_metadata (
    document_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(255),
    status VARCHAR(50) DEFAULT 'uploaded',
    processing_result JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    file_path VARCHAR(1024)
);

COMMENT ON TABLE document_metadata IS '文档元数据表';
COMMENT ON COLUMN document_metadata.document_id IS '文档ID';
COMMENT ON COLUMN document_metadata.user_id IS '用户ID';
COMMENT ON COLUMN document_metadata.filename IS '文件名';
COMMENT ON COLUMN document_metadata.file_hash IS '文件哈希值';
COMMENT ON COLUMN document_metadata.file_size IS '文件大小（字节）';
COMMENT ON COLUMN document_metadata.mime_type IS 'MIME类型';
COMMENT ON COLUMN document_metadata.status IS '状态（uploaded, processing, completed, failed）';
COMMENT ON COLUMN document_metadata.processing_result IS '处理结果（JSON格式）';
COMMENT ON COLUMN document_metadata.metadata IS '元数据（JSON格式）';
COMMENT ON COLUMN document_metadata.created_at IS '创建时间';
COMMENT ON COLUMN document_metadata.processed_at IS '处理时间';
COMMENT ON COLUMN document_metadata.file_path IS '文件存储路径';

CREATE INDEX IF NOT EXISTS idx_document_metadata_user_id ON document_metadata (user_id);
CREATE INDEX IF NOT EXISTS idx_document_metadata_filename ON document_metadata (filename);
CREATE INDEX IF NOT EXISTS idx_document_metadata_file_hash ON document_metadata (file_hash);
CREATE INDEX IF NOT EXISTS idx_document_metadata_status ON document_metadata (status);
CREATE INDEX IF NOT EXISTS idx_document_metadata_created_at ON document_metadata (created_at DESC);

-- ============================================================================
-- 创建向量嵌入表
-- ============================================================================

CREATE TABLE IF NOT EXISTS vector_embeddings (
    embedding_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding_vector FLOAT[] NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE vector_embeddings IS '向量嵌入表';
COMMENT ON COLUMN vector_embeddings.embedding_id IS '嵌入ID';
COMMENT ON COLUMN vector_embeddings.user_id IS '用户ID';
COMMENT ON COLUMN vector_embeddings.content IS '原始内容';
COMMENT ON COLUMN vector_embeddings.embedding_vector IS '嵌入向量';
COMMENT ON COLUMN vector_embeddings.model_name IS '模型名称';
COMMENT ON COLUMN vector_embeddings.metadata IS '元数据（JSON格式）';
COMMENT ON COLUMN vector_embeddings.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_vector_embeddings_user_id ON vector_embeddings (user_id);
CREATE INDEX IF NOT EXISTS idx_vector_embeddings_model_name ON vector_embeddings (model_name);
CREATE INDEX IF NOT EXISTS idx_vector_embeddings_created_at ON vector_embeddings (created_at DESC);

-- ============================================================================
-- 创建系统指标表
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_metrics (
    metric_id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    metric_name VARCHAR(200) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE system_metrics IS '系统指标表';
COMMENT ON COLUMN system_metrics.metric_id IS '指标ID';
COMMENT ON COLUMN system_metrics.service_name IS '服务名称';
COMMENT ON COLUMN system_metrics.metric_name IS '指标名称';
COMMENT ON COLUMN system_metrics.metric_value IS '指标值';
COMMENT ON COLUMN system_metrics.labels IS '标签（JSON格式）';
COMMENT ON COLUMN system_metrics.timestamp IS '时间戳';

CREATE INDEX IF NOT EXISTS idx_system_metrics_service_name ON system_metrics (service_name);
CREATE INDEX IF NOT EXISTS idx_system_metrics_metric_name ON system_metrics (metric_name);
CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp ON system_metrics (timestamp DESC);

-- ============================================================================
-- 创建审计日志表
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    details JSONB DEFAULT '{}'::jsonb,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE audit_logs IS '审计日志表';
COMMENT ON COLUMN audit_logs.log_id IS '日志ID';
COMMENT ON COLUMN audit_logs.user_id IS '用户ID';
COMMENT ON COLUMN audit_logs.action IS '操作类型';
COMMENT ON COLUMN audit_logs.resource_type IS '资源类型';
COMMENT ON COLUMN audit_logs.resource_id IS '资源ID';
COMMENT ON COLUMN audit_logs.details IS '详细信息（JSON格式）';
COMMENT ON COLUMN audit_logs.ip_address IS 'IP地址';
COMMENT ON COLUMN audit_logs.user_agent IS '用户代理';
COMMENT ON COLUMN audit_logs.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type ON audit_logs (resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at DESC);

-- ============================================================================
-- 创建函数和触发器
-- ============================================================================

-- 自动更新updated_at字段的函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 自动更新modified_at字段的函数
CREATE OR REPLACE FUNCTION update_modified_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为所有需要自动更新时间的表创建触发器（幂等）
DROP TRIGGER IF EXISTS update_workspaces_updated_at ON workspaces;
CREATE TRIGGER update_workspaces_updated_at BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_workspace_files_updated_at ON workspace_files;
CREATE TRIGGER update_workspace_files_updated_at BEFORE UPDATE ON workspace_files
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_workflow_tasks_updated_at ON workflow_tasks;
CREATE TRIGGER update_workflow_tasks_updated_at BEFORE UPDATE ON workflow_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_cards_modified_at ON cards;
CREATE TRIGGER update_cards_modified_at BEFORE UPDATE ON cards
    FOR EACH ROW EXECUTE FUNCTION update_modified_at_column();

-- ============================================================================
-- 创建视图
-- ============================================================================

-- 工作流任务统计视图
CREATE OR REPLACE VIEW workflow_stats AS
SELECT
    workflow_type,
    status,
    COUNT(*) as task_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds,
    MIN(created_at) as first_task,
    MAX(created_at) as last_task
FROM workflow_tasks
GROUP BY workflow_type, status;

-- 用户活动统计视图
CREATE OR REPLACE VIEW user_activity_stats AS
SELECT
    user_id,
    COUNT(DISTINCT CASE WHEN source = 'workflow' THEN id END) as total_tasks,
    COUNT(DISTINCT CASE WHEN source = 'card' THEN id END) as total_cards,
    COUNT(DISTINCT CASE WHEN source = 'document' THEN id END) as total_documents,
    MIN(created_at) as first_activity,
    MAX(created_at) as last_activity
FROM (
    SELECT user_id, task_id as id, created_at, 'workflow' as source FROM workflow_tasks
    UNION ALL
    SELECT user_id, card_id as id, created_at, 'card' as source FROM cards
    UNION ALL
    SELECT user_id, document_id as id, created_at, 'document' as source FROM document_metadata
) activities
GROUP BY user_id;

-- ============================================================================
-- 插入初始数据（可选）
-- ============================================================================

-- 插入系统用户（如果需要）
-- INSERT INTO workspaces (workspace_id, user_id, storage_path, minio_bucket, metadata)
-- VALUES (
--     'system-workspace',
--     'system',
--     'workspaces/system',
--     'system-bucket',
--     '{"description": "System workspace"}'::jsonb
-- );

-- ============================================================================
-- 创建角色和权限（生产环境需要）
-- ============================================================================

-- 创建只读角色
-- CREATE ROLE kardcraft_readonly;
-- GRANT CONNECT ON DATABASE kardcraft TO kardcraft_readonly;
-- GRANT USAGE ON SCHEMA public TO kardcraft_readonly;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO kardcraft_readonly;

-- 创建读写角色
-- CREATE ROLE kardcraft_readwrite;
-- GRANT CONNECT ON DATABASE kardcraft TO kardcraft_readwrite;
-- GRANT USAGE ON SCHEMA public TO kardcraft_readwrite;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kardcraft_readwrite;

-- ============================================================================
-- 完成消息
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Kardcraft 数据库初始化完成！';
    RAISE NOTICE '已创建的表：';
    RAISE NOTICE '  - workspaces (工作空间表)';
    RAISE NOTICE '  - workspace_files (工作空间文件表)';
    RAISE NOTICE '  - workflow_tasks (工作流任务表)';
    RAISE NOTICE '  - cards (卡片表)';
    RAISE NOTICE '  - document_metadata (文档元数据表)';
    RAISE NOTICE '  - vector_embeddings (向量嵌入表)';
    RAISE NOTICE '  - system_metrics (系统指标表)';
    RAISE NOTICE '  - audit_logs (审计日志表)';
    RAISE NOTICE '';
    RAISE NOTICE '已创建的视图：';
    RAISE NOTICE '  - workflow_stats (工作流统计视图)';
    RAISE NOTICE '  - user_activity_stats (用户活动统计视图)';
    RAISE NOTICE '';
    RAISE NOTICE '已创建的触发器：';
    RAISE NOTICE '  - 自动更新updated_at字段的触发器';
END $$;
