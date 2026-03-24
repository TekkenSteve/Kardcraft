"""
Redis客户端
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Union

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError, ConnectionError

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis客户端"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 10,
        socket_timeout: float = 5.0,
        socket_connect_timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout

        self.client: Optional[Redis] = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._reconnect_delay = 1.0

    async def connect(self):
        """连接到Redis"""
        async with self._lock:
            if self._connected:
                return

            logger.info(f"Connecting to Redis at {self.host}:{self.port} (db={self.db})...")

            try:
                # 创建Redis连接池
                self.client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    max_connections=self.max_connections,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout,
                    decode_responses=True,  # 自动解码字符串
                    health_check_interval=30,  # 健康检查间隔
                )

                # 测试连接
                await self._test_connection()

                self._connected = True
                self._reconnect_attempts = 0
                logger.info(f"Connected to Redis at {self.host}:{self.port} (db={self.db})")

            except Exception as e:
                logger.error(f"Failed to connect to Redis at {self.host}:{self.port}: {e}")
                await self._cleanup()
                raise

    async def close(self):
        """关闭连接"""
        async with self._lock:
            if not self._connected:
                return

            logger.info(f"Closing Redis connection to {self.host}:{self.port}...")

            try:
                if self.client:
                    await self.client.close()
            except Exception as e:
                logger.warning(f"Error while closing Redis connection: {e}")

            self.client = None
            self._connected = False
            logger.info(f"Redis connection closed")

    async def ping(self) -> bool:
        """Ping Redis服务器"""
        try:
            if not self._connected or not self.client:
                return False

            result = await self.client.ping()
            return result is True

        except Exception as e:
            logger.warning(f"Redis ping failed: {e}")
            return False

    async def get(self, key: str) -> Optional[str]:
        """获取键值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.get(key)

        except Exception as e:
            logger.error(f"Redis get failed for key {key}: {e}")
            await self._handle_error(e)
            return None

    async def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """设置键值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            result = await self.client.set(
                key, value,
                ex=ex, px=px, nx=nx, xx=xx
            )
            return result is True

        except Exception as e:
            logger.error(f"Redis set failed for key {key}: {e}")
            await self._handle_error(e)
            return False

    async def set_json(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """设置JSON值"""
        try:
            json_value = json.dumps(value, ensure_ascii=False)
            return await self.set(key, json_value, ex=ex, px=px, nx=nx, xx=xx)
        except Exception as e:
            logger.error(f"Redis set_json failed for key {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Any]:
        """获取JSON值"""
        try:
            value = await self.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get_json failed for key {key}: {e}")
            return None

    async def delete(self, *keys: str) -> int:
        """删除键"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.delete(*keys)

        except Exception as e:
            logger.error(f"Redis delete failed for keys {keys}: {e}")
            await self._handle_error(e)
            return 0

    async def exists(self, *keys: str) -> int:
        """检查键是否存在"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.exists(*keys)

        except Exception as e:
            logger.error(f"Redis exists failed for keys {keys}: {e}")
            await self._handle_error(e)
            return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """设置键过期时间"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.expire(key, seconds)

        except Exception as e:
            logger.error(f"Redis expire failed for key {key}: {e}")
            await self._handle_error(e)
            return False

    async def ttl(self, key: str) -> int:
        """获取键的剩余生存时间"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.ttl(key)

        except Exception as e:
            logger.error(f"Redis ttl failed for key {key}: {e}")
            await self._handle_error(e)
            return -2  # 键不存在

    async def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """增加键的值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            if amount == 1:
                return await self.client.incr(key)
            else:
                return await self.client.incrby(key, amount)

        except Exception as e:
            logger.error(f"Redis incr failed for key {key}: {e}")
            await self._handle_error(e)
            return None

    async def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """减少键的值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            if amount == 1:
                return await self.client.decr(key)
            else:
                return await self.client.decrby(key, amount)

        except Exception as e:
            logger.error(f"Redis decr failed for key {key}: {e}")
            await self._handle_error(e)
            return None

    async def incrby(self, key: str, amount: int) -> Optional[int]:
        """按指定数量增加键的值"""
        return await self.incr(key, amount)

    async def decrby(self, key: str, amount: int) -> Optional[int]:
        """按指定数量减少键的值"""
        return await self.decr(key, amount)

    async def hset(self, key: str, field: str, value: str) -> bool:
        """设置哈希字段"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            result = await self.client.hset(key, field, value)
            return result == 1

        except Exception as e:
            logger.error(f"Redis hset failed for key {key}, field {field}: {e}")
            await self._handle_error(e)
            return False

    async def hget(self, key: str, field: str) -> Optional[str]:
        """获取哈希字段"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.hget(key, field)

        except Exception as e:
            logger.error(f"Redis hget failed for key {key}, field {field}: {e}")
            await self._handle_error(e)
            return None

    async def hgetall(self, key: str) -> Dict[str, str]:
        """获取所有哈希字段"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.hgetall(key)

        except Exception as e:
            logger.error(f"Redis hgetall failed for key {key}: {e}")
            await self._handle_error(e)
            return {}

    async def hdel(self, key: str, *fields: str) -> int:
        """删除哈希字段"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.hdel(key, *fields)

        except Exception as e:
            logger.error(f"Redis hdel failed for key {key}, fields {fields}: {e}")
            await self._handle_error(e)
            return 0

    async def sadd(self, key: str, *members: str) -> int:
        """向集合添加成员"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.sadd(key, *members)

        except Exception as e:
            logger.error(f"Redis sadd failed for key {key}: {e}")
            await self._handle_error(e)
            return 0

    async def smembers(self, key: str) -> set:
        """获取集合所有成员"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.smembers(key)

        except Exception as e:
            logger.error(f"Redis smembers failed for key {key}: {e}")
            await self._handle_error(e)
            return set()

    async def srem(self, key: str, *members: str) -> int:
        """从集合移除成员"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.srem(key, *members)

        except Exception as e:
            logger.error(f"Redis srem failed for key {key}: {e}")
            await self._handle_error(e)
            return 0

    async def lpush(self, key: str, *values: str) -> int:
        """向列表头部添加值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.lpush(key, *values)

        except Exception as e:
            logger.error(f"Redis lpush failed for key {key}: {e}")
            await self._handle_error(e)
            return 0

    async def rpush(self, key: str, *values: str) -> int:
        """向列表尾部添加值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.rpush(key, *values)

        except Exception as e:
            logger.error(f"Redis rpush failed for key {key}: {e}")
            await self._handle_error(e)
            return 0

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """获取列表范围"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.lrange(key, start, end)

        except Exception as e:
            logger.error(f"Redis lrange failed for key {key}: {e}")
            await self._handle_error(e)
            return []

    async def lpop(self, key: str) -> Optional[str]:
        """从列表头部弹出值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.lpop(key)

        except Exception as e:
            logger.error(f"Redis lpop failed for key {key}: {e}")
            await self._handle_error(e)
            return None

    async def rpop(self, key: str) -> Optional[str]:
        """从列表尾部弹出值"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.rpop(key)

        except Exception as e:
            logger.error(f"Redis rpop failed for key {key}: {e}")
            await self._handle_error(e)
            return None

    async def publish(self, channel: str, message: str) -> int:
        """发布消息到频道"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.publish(channel, message)

        except Exception as e:
            logger.error(f"Redis publish failed for channel {channel}: {e}")
            await self._handle_error(e)
            return 0

    async def subscribe(self, *channels: str):
        """订阅频道"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            pubsub = self.client.pubsub()
            await pubsub.subscribe(*channels)
            return pubsub

        except Exception as e:
            logger.error(f"Redis subscribe failed for channels {channels}: {e}")
            await self._handle_error(e)
            raise

    async def keys(self, pattern: str = "*") -> List[str]:
        """查找匹配模式的键"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.keys(pattern)

        except Exception as e:
            logger.error(f"Redis keys failed for pattern {pattern}: {e}")
            await self._handle_error(e)
            return []

    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: Optional[int] = None):
        """迭代键"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return await self.client.scan(cursor, match, count)

        except Exception as e:
            logger.error(f"Redis scan failed: {e}")
            await self._handle_error(e)
            return (0, [])

    async def flushdb(self) -> bool:
        """清空当前数据库"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            await self.client.flushdb()
            return True

        except Exception as e:
            logger.error(f"Redis flushdb failed: {e}")
            await self._handle_error(e)
            return False

    async def info(self, section: Optional[str] = None) -> Dict[str, Any]:
        """获取Redis服务器信息"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            info_str = await self.client.info(section)
            return info_str

        except Exception as e:
            logger.error(f"Redis info failed: {e}")
            await self._handle_error(e)
            return {}

    async def pipeline(self):
        """创建管道"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return self.client.pipeline()

        except Exception as e:
            logger.error(f"Redis pipeline creation failed: {e}")
            await self._handle_error(e)
            raise

    async def transaction(self, *args, **kwargs):
        """创建事务"""
        try:
            if not self._connected or not self.client:
                raise ConnectionError("Not connected to Redis")

            return self.client.multi_exec(*args, **kwargs)

        except Exception as e:
            logger.error(f"Redis transaction creation failed: {e}")
            await self._handle_error(e)
            raise

    # ============================================================================
    # 私有方法
    # ============================================================================

    async def _test_connection(self):
        """测试连接"""
        try:
            # 尝试ping
            pong = await self.client.ping()
            if not pong:
                raise ConnectionError("Redis ping failed")
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            await self._cleanup()
            raise

    async def _handle_error(self, error: Exception):
        """处理错误"""
        if isinstance(error, ConnectionError):
            logger.warning("Redis connection error, attempting to reconnect...")
            await self._attempt_reconnect()
        else:
            logger.error(f"Redis operation error: {error}")

    async def _attempt_reconnect(self):
        """尝试重新连接"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return

        self._reconnect_attempts += 1
        delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))

        logger.info(f"Attempting to reconnect to Redis (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}) in {delay}s...")

        await asyncio.sleep(delay)

        try:
            await self._cleanup()
            await self.connect()
        except Exception as e:
            logger.error(f"Reconnection attempt {self._reconnect_attempts} failed: {e}")

    async def _cleanup(self):
        """清理资源"""
        try:
            if self.client:
                await self.client.close()
        except Exception:
            pass

        self.client = None
        self._connected = False