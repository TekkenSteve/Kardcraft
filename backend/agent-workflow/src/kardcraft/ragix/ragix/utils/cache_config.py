"""
统一的缓存配置管理

这个模块提供了 ragix 模块的缓存配置，与主项目的 runtime_cache 保持一致。
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
    return CACHE_TTL_CONFIG.get(cache_type, 1800)  # 默认30分钟

# 缓存策略配置
CACHE_STRATEGIES = {
    # 解析器实例：内存优先，Redis 作为配置缓存
    "parser_instance": {
        "memory": True,
        "redis": "config_only",  # 只缓存配置，不缓存实例
        "ttl": CACHE_TTL_CONFIG["parser_config"]
    },
    
    # 模型实例：内存优先，Redis 作为备份
    "model_instance": {
        "memory": True,
        "redis": "metadata_only",  # 只缓存元数据
        "ttl": CACHE_TTL_CONFIG["embedding_model"]
    },
    
    # 处理结果：Redis 优先
    "processing_result": {
        "memory": False,
        "redis": True,
        "ttl": CACHE_TTL_CONFIG["parse_result"]
    }
}

def should_cache_to_redis(cache_type: str) -> bool:
    """判断是否应该缓存到 Redis"""
    strategy = CACHE_STRATEGIES.get(cache_type, {})
    redis_strategy = strategy.get("redis", True)
    return redis_strategy is True or redis_strategy in ["config_only", "metadata_only"]

def should_cache_to_memory(cache_type: str) -> bool:
    """判断是否应该缓存到内存"""
    strategy = CACHE_STRATEGIES.get(cache_type, {})
    return strategy.get("memory", True)