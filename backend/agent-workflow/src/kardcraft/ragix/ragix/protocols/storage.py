# protocols/storage.py - 存储组件协议
"""
存储组件协议定义

支持多种存储后端：MinIO、S3、本地文件系统等
参考RAGFlow的MinIO实现，但更通用
"""

from typing import Protocol, runtime_checkable, Dict, Any, Optional, List
from dataclasses import dataclass
from .component import Component, ComponentConfig, HealthStatus, HealthCheckable


@dataclass
class StorageConfig(ComponentConfig):
    """存储配置"""
    provider: str = "minio"  # "minio", "s3", "local", "memory"
    endpoint: Optional[str] = None  # 存储服务端点
    access_key: Optional[str] = None  # 访问密钥
    secret_key: Optional[str] = None  # 秘密密钥
    region: Optional[str] = None  # 区域（S3）
    bucket: Optional[str] = None  # 默认桶（单桶模式）
    prefix_path: Optional[str] = None  # 前缀路径
    secure: bool = False  # 是否使用安全连接
    use_backend_service: bool = True  # 是否使用backend/file-storage服务

    # 连接参数
    max_retries: int = 3
    timeout: int = 30
    pool_size: int = 10

    def __post_init__(self):
        super().__post_init__()
        # 设置默认参数
        if self.provider == "minio" and not self.endpoint:
            self.endpoint = "localhost:9000"
        elif self.provider == "s3" and not self.endpoint:
            self.endpoint = "s3.amazonaws.com"


@runtime_checkable
class Storage(Component, HealthCheckable, Protocol):
    """存储组件协议"""

    async def put(self, bucket: str, key: str, data: bytes, **kwargs) -> bool:
        """上传文件

        Args:
            bucket: 桶名
            key: 文件键
            data: 文件数据
            **kwargs: 额外参数

        Returns:
            bool: 是否成功
        """
        ...

    async def get(self, bucket: str, key: str, **kwargs) -> bytes:
        """下载文件

        Args:
            bucket: 桶名
            key: 文件键

        Returns:
            bytes: 文件数据
        """
        ...

    async def delete(self, bucket: str, key: str, **kwargs) -> bool:
        """删除文件

        Args:
            bucket: 桶名
            key: 文件键

        Returns:
            bool: 是否成功
        """
        ...

    async def list(self, bucket: str, prefix: str = "", **kwargs) -> List[str]:
        """列出文件

        Args:
            bucket: 桶名
            prefix: 前缀

        Returns:
            List[str]: 文件键列表
        """
        ...

    async def exists(self, bucket: str, key: str, **kwargs) -> bool:
        """检查文件是否存在

        Args:
            bucket: 桶名
            key: 文件键

        Returns:
            bool: 是否存在
        """
        ...

    async def stat(self, bucket: str, key: str, **kwargs) -> Dict[str, Any]:
        """获取文件信息

        Args:
            bucket: 桶名
            key: 文件键

        Returns:
            Dict: 文件信息
        """
        ...

    async def check_health(self) -> HealthStatus:
        """检查存储服务健康状态"""
        ...


# 装饰器（类似RAGFlow的实现）

def use_default_bucket(method):
    """默认桶装饰器 - 单桶模式下使用默认桶"""
    async def wrapper(self, bucket: str, *args, **kwargs):
        config = self.get_config()
        if config.bucket:
            # 单桶模式：使用配置的默认桶
            actual_bucket = config.bucket
            kwargs['_orig_bucket'] = bucket  # 传递原始桶名用于路径构造
        else:
            actual_bucket = bucket

        return await method(self, actual_bucket, *args, **kwargs)
    return wrapper


def use_prefix_path(method):
    """前缀路径装饰器 - 添加前缀路径"""
    async def wrapper(self, bucket: str, key: str, *args, **kwargs):
        config = self.get_config()
        orig_bucket = kwargs.pop('_orig_bucket', None)

        if config.prefix_path:
            # 如果有前缀路径
            if orig_bucket:
                # 单桶模式：使用原始桶名作为路径部分
                key = f"{config.prefix_path}/{orig_bucket}/{key}"
            else:
                key = f"{config.prefix_path}/{key}"
        elif orig_bucket and bucket == config.bucket:
            # 单桶模式但没有前缀路径：使用原始桶名作为路径
            key = f"{orig_bucket}/{key}"

        return await method(self, bucket, key, *args, **kwargs)
    return wrapper


# 存储模式枚举
class StorageMode(str):
    """存储模式"""
    SINGLE_BUCKET = "single_bucket"  # 单桶模式
    MULTI_BUCKET = "multi_bucket"    # 多桶模式


@dataclass
class StorageStats:
    """存储统计信息"""
    total_files: int = 0
    total_size: int = 0
    bucket_count: int = 0
    last_sync_time: Optional[str] = None