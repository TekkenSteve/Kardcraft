"""
统一的缓存配置管理

"""
import os
from typing import Dict, Any, Optional

# 缓存 TTL 配置（秒）
CACHE_TTL_CONFIG = {
    # 解析器相关缓存
    "parser_config": int(os.getenv("RAGIX_PARSER_CONFIG_TTL", "3600")),  # 1小时
    "parser_instance": int(os.getenv("RAGIX_PARSER_INSTANCE_TTL", "1800")),  # 30分钟
    
    # 模型相关缓存
    "embedding_model": int(os.getenv("RAGIX_EMBEDDING_MODEL_TTL", "7200")),  # 2小时
    "reranker_model": int(os.getenv("RAGIX_RERANKER_MODEL_TTL", "7200")),  # 2小时
    "tokenizer": int(os.getenv("RAGIX_TOKENIZER_TTL", "7200")),  # 2小时
    
    # 处理结果缓存
    "parse_result": int(os.getenv("RAGIX_PARSE_RESULT_TTL", "1800")),  # 30分钟
    "embedding_result": int(os.getenv("RAGIX_EMBEDDING_RESULT_TTL", "3600")),  # 1小时
    
    # 配置缓存
    "component_config": int(os.getenv("RAGIX_COMPONENT_CONFIG_TTL", "3600")),  # 1小时
    "registry_config": int(os.getenv("RAGIX_REGISTRY_CONFIG_TTL", "1800")),  # 30分钟
}

# Redis 键前缀配置
CACHE_KEY_PREFIXES = {
    "parser": "ragix:parser",
    "model": "ragix:model", 
    "result": "ragix:result",
    "config": "ragix:config",
}

def get_cache_key(category: str, identifier: str) -> str:
    """生成标准化的缓存键"""
    prefix = CACHE_KEY_PREFIXES.get(category, f"ragix:{category}")
    return f"{prefix}:{identifier}"

def get_cache_ttl(cache_type: str) -> int:
    """获取指定缓存类型的 TTL"""
    return CACHE_TTL_CONFIG.get(cache_type, 1800)  # Default 30 minutes

# Cache Policy Configuration
CACHE_STRATEGIES = {
    # Parser instance: memory-first, Redis as configuration cache
    "parser_instance": {
        "memory": True,
        "redis": "config_only",  # Cache only configuration, not instances
        "ttl": CACHE_TTL_CONFIG["parser_config"]
    },
    
    # Model example: memory-first, Redis as a backup
    "model_instance": {
        "memory": True,
        "redis": "metadata_only",  # Cache only metadata
        "ttl": CACHE_TTL_CONFIG["embedding_model"]
    },
    
    # Processing result: Redis preferred
    "processing_result": {
        "memory": False,
        "redis": True,
        "ttl": CACHE_TTL_CONFIG["parse_result"]
    }
}

def should_cache_to_redis(cache_type: str) -> bool:
    """Determine whether it should be cached to Redis"""
    strategy = CACHE_STRATEGIES.get(cache_type, {})
    redis_strategy = strategy.get("redis", True)
    return redis_strategy is True or redis_strategy in ["config_only", "metadata_only"]

def should_cache_to_memory(cache_type: str) -> bool:
    """Determine whether it should be cached in memory"""
    strategy = CACHE_STRATEGIES.get(cache_type, {})
    return strategy.get("memory", True)