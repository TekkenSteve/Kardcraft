# core/config.py - LightRAG server config only

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# TODO: 去 .env.ragix 里添加示例配置项
class LightRAGServerConfig(BaseSettings):
    """LightRAG 服务器配置（REST Server）"""

    base_url: str = (
        os.getenv("LIGHTRAG_BASE_URL")
        or os.getenv("RAGIX_LIGHTRAG_BASE_URL")
        or "http://localhost:9621"
    )
    api_key: Optional[str] = None
    timeout: int = 150
    max_retries: int = 3
    retry_delay: float = 1.0

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",  # 临时
    )
