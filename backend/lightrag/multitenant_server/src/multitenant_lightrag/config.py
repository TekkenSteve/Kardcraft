from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    listen_host: str = os.getenv("LIGHTRAG_MT_HOST", "0.0.0.0")
    listen_port: int = int(os.getenv("LIGHTRAG_MT_PORT", "9621"))
    log_level: str = os.getenv("LIGHTRAG_MT_LOG_LEVEL", "info").lower()

    upstream_timeout_sec: float = float(os.getenv("LIGHTRAG_UPSTREAM_TIMEOUT_SEC", "300"))
    process_cmd: str = os.getenv("LIGHTRAG_PROCESS_CMD", "lightrag-server")
    process_bind_host: str = os.getenv("LIGHTRAG_PROCESS_BIND_HOST", "127.0.0.1")
    process_base_port: int = int(os.getenv("LIGHTRAG_PROCESS_BASE_PORT", "29621"))
    process_startup_timeout_sec: float = float(os.getenv("LIGHTRAG_PROCESS_STARTUP_TIMEOUT_SEC", "45"))
    workspaces_root: str = os.getenv("LIGHTRAG_WORKSPACES_ROOT", "/data/lightrag_workspaces")
    template_env_file: str = os.getenv("LIGHTRAG_TEMPLATE_ENV_FILE", "/app/.env.lightrag")

    default_workspace: str = os.getenv("LIGHTRAG_DEFAULT_WORKSPACE", "default")
    enforce_workspace_header: bool = os.getenv("LIGHTRAG_ENFORCE_WORKSPACE_HEADER", "false").lower() == "true"

    pool_size_per_workspace: int = int(os.getenv("LIGHTRAG_POOL_SIZE_PER_WORKSPACE", "4"))
    max_workspace_count: int = int(os.getenv("LIGHTRAG_MAX_WORKSPACE_COUNT", "200"))
    borrow_timeout_sec: float = float(os.getenv("LIGHTRAG_BORROW_TIMEOUT_SEC", "10"))

    global_max_inflight: int = int(os.getenv("LIGHTRAG_GLOBAL_MAX_INFLIGHT", "128"))
    per_workspace_max_inflight: int = int(os.getenv("LIGHTRAG_PER_WORKSPACE_MAX_INFLIGHT", "16"))

    api_key: str | None = os.getenv("LIGHTRAG_API_KEY")
    purge_data_on_evict: bool = os.getenv("LIGHTRAG_PURGE_DATA_ON_EVICT", "true").lower() == "true"
    delete_workspace_dir_on_evict: bool = (
        os.getenv("LIGHTRAG_DELETE_WORKSPACE_DIR_ON_EVICT", "true").lower() == "true"
    )
