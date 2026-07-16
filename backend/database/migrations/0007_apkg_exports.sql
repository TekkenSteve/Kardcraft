CREATE TABLE kc_apkg_exports (
    export_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES kc_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    template_id VARCHAR(128) NOT NULL,
    deck_name VARCHAR(255) NOT NULL DEFAULT '',
    package_name VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL,
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    file_name VARCHAR(512) NOT NULL DEFAULT '',
    file_size BIGINT NOT NULL DEFAULT 0,
    apkg_bytes BYTEA,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_kc_apkg_exports_status CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    CONSTRAINT ck_kc_apkg_exports_confirmed_count CHECK (confirmed_count >= 0),
    CONSTRAINT ck_kc_apkg_exports_file_size CHECK (file_size >= 0)
);

CREATE INDEX idx_kc_apkg_exports_session_user
    ON kc_apkg_exports (session_id, user_id, created_at DESC);

CREATE INDEX idx_kc_apkg_exports_status
    ON kc_apkg_exports (status, updated_at);
