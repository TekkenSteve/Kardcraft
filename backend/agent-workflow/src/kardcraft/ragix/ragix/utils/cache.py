import json
from datetime import datetime, date
from typing import Any, Optional
from ..services.redis import get_client
from .cache_config import get_cache_key, get_cache_ttl


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        return super().default(o)


class _cache:
    async def get(self, key: str, category: str = "default"):
        """获取缓存，使用统一的键命名规范"""
        redis = await get_client()
        cache_key = get_cache_key(category, key)
        result = await redis.get(cache_key)
        if result:
            return json.loads(result)
        return None

    async def set(self, key: str, value: Any, category: str = "default", 
                  ttl: Optional[int] = None):
        """设置缓存，使用统一的 TTL 配置"""
        redis = await get_client()
        cache_key = get_cache_key(category, key)
        if ttl is None:
            ttl = get_cache_ttl("component_config")  # 默认使用组件配置 TTL
        await redis.set(cache_key, json.dumps(value, cls=DateTimeEncoder), ex=ttl)

    async def invalidate(self, key: str, category: str = "default"):
        """失效缓存"""
        redis = await get_client()
        cache_key = get_cache_key(category, key)
        await redis.delete(cache_key)
    
    async def invalidate_multiple(self, keys: list[str], category: str = "default"):
        """批量失效缓存"""
        from ..services.redis import delete_multiple
        cache_keys = [get_cache_key(category, key) for key in keys]
        await delete_multiple(cache_keys, timeout=5.0)


Cache = _cache()
