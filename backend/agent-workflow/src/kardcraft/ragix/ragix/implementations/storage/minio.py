# implementations/storage/minio.py - MinIO存储实现
"""
MinIO存储实现

支持与backend/file-storage集成，或直接使用MinIO客户端
参考RAGFlow的MinIO实现
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional
from io import BytesIO

from ...protocols.storage import (
    Storage, StorageConfig, use_default_bucket, use_prefix_path,
    HealthStatus, StorageMode
)
from ...protocols.component import BaseComponent

# 尝试导入backend/file-storage
try:
    # 假设backend/file-storage提供客户端
    # from backend.file_storage import MinioClient as BackendMinioClient
    HAS_BACKEND_STORAGE = False
except ImportError:
    HAS_BACKEND_STORAGE = False

# 尝试导入MinIO客户端
try:
    from minio import Minio
    from minio.error import S3Error, ServerError, InvalidResponseError
    HAS_MINIO_LIB = True
except ImportError:
    HAS_MINIO_LIB = False


class MinIOStorage(BaseComponent, Storage):
    """MinIO存储实现"""

    def __init__(self, config: StorageConfig):
        super().__init__(config)
        self.config: StorageConfig = config
        self._client = None
        self._initialized = False

    async def _do_initialize(self) -> bool:
        """初始化MinIO客户端"""
        try:
            if self.config.use_backend_service and HAS_BACKEND_STORAGE:
                # 使用backend/file-storage服务
                self._client = "backend"  # 标记使用后端服务
                logging.info("Using backend/file-storage service for MinIO operations")
            elif HAS_MINIO_LIB:
                # 直接使用MinIO客户端
                self._client = Minio(
                    endpoint=self.config.endpoint,
                    access_key=self.config.access_key,
                    secret_key=self.config.secret_key,
                    secure=self.config.secure,
                    region=self.config.region
                )
                logging.info(f"Initialized MinIO client for {self.config.endpoint}")
            else:
                logging.error("No MinIO client available. Please install minio package or configure backend service.")
                return False

            # 检查连接
            health_status = await self.check_health()
            if not health_status.is_healthy:
                logging.warning(f"MinIO health check failed: {health_status.message}")
                # 仍然返回True，允许延迟连接
            return True

        except Exception as e:
            logging.error(f"Failed to initialize MinIO storage: {e}")
            return False

    async def _do_shutdown(self) -> None:
        """关闭MinIO客户端"""
        self._client = None
        self._initialized = False

    @use_default_bucket
    @use_prefix_path
    async def put(self, bucket: str, key: str, data: bytes, **kwargs) -> bool:
        """上传文件"""
        max_retries = kwargs.get('max_retries', self.config.max_retries)

        for attempt in range(max_retries):
            try:
                if self._client == "backend":
                    # 调用backend/file-storage服务
                    # result = await backend.file_storage.upload(bucket, key, data)
                    # return result.success
                    # 暂时模拟成功
                    logging.info(f"[Backend] Upload to {bucket}/{key}, size: {len(data)} bytes")
                    return True
                else:
                    # 直接使用MinIO客户端
                    result = self._client.put_object(
                        bucket_name=bucket,
                        object_name=key,
                        data=BytesIO(data),
                        length=len(data)
                    )
                    logging.info(f"Uploaded to {bucket}/{key}, etag: {result.etag}")
                    return True

            except Exception as e:
                logging.error(f"Upload attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # 重试前等待
                    # 尝试重新连接
                    await self._reconnect()
                else:
                    raise

        return False

    @use_default_bucket
    @use_prefix_path
    async def get(self, bucket: str, key: str, **kwargs) -> bytes:
        """下载文件"""
        max_retries = kwargs.get('max_retries', self.config.max_retries)

        for attempt in range(max_retries):
            try:
                if self._client == "backend":
                    # 调用backend/file-storage服务
                    # data = await backend.file_storage.download(bucket, key)
                    # return data
                    # 暂时模拟返回空数据
                    logging.info(f"[Backend] Download from {bucket}/{key}")
                    return b""
                else:
                    # 直接使用MinIO客户端
                    response = self._client.get_object(bucket, key)
                    data = response.read()
                    response.close()
                    response.release_conn()
                    return data

            except Exception as e:
                logging.error(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    await self._reconnect()
                else:
                    raise

        return b""

    @use_default_bucket
    @use_prefix_path
    async def delete(self, bucket: str, key: str, **kwargs) -> bool:
        """删除文件"""
        try:
            if self._client == "backend":
                # 调用backend/file-storage服务
                # result = await backend.file_storage.delete(bucket, key)
                # return result.success
                logging.info(f"[Backend] Delete {bucket}/{key}")
                return True
            else:
                self._client.remove_object(bucket, key)
                logging.info(f"Deleted {bucket}/{key}")
                return True

        except Exception as e:
            logging.error(f"Delete failed: {e}")
            return False

    async def list(self, bucket: str, prefix: str = "", **kwargs) -> List[str]:
        """列出文件"""
        try:
            if self._client == "backend":
                # 调用backend/file-storage服务
                # items = await backend.file_storage.list(bucket, prefix)
                # return items
                logging.info(f"[Backend] List {bucket}/{prefix}")
                return []
            else:
                objects = self._client.list_objects(bucket, prefix=prefix, recursive=True)
                return [obj.object_name for obj in objects]

        except Exception as e:
            logging.error(f"List failed: {e}")
            return []

    async def exists(self, bucket: str, key: str, **kwargs) -> bool:
        """检查文件是否存在"""
        try:
            if self._client == "backend":
                # 调用backend/file-storage服务
                # exists = await backend.file_storage.exists(bucket, key)
                # return exists
                logging.info(f"[Backend] Check exists {bucket}/{key}")
                return False
            else:
                # MinIO没有直接的exists方法，通过stat检查
                try:
                    self._client.stat_object(bucket, key)
                    return True
                except S3Error as e:
                    if e.code == "NoSuchKey":
                        return False
                    raise

        except Exception as e:
            logging.error(f"Exists check failed: {e}")
            return False

    async def stat(self, bucket: str, key: str, **kwargs) -> Dict[str, Any]:
        """获取文件信息"""
        try:
            if self._client == "backend":
                # 调用backend/file-storage服务
                # stat = await backend.file_storage.stat(bucket, key)
                # return stat
                logging.info(f"[Backend] Stat {bucket}/{key}")
                return {}
            else:
                stat = self._client.stat_object(bucket, key)
                return {
                    "size": stat.size,
                    "etag": stat.etag,
                    "last_modified": stat.last_modified,
                    "content_type": stat.content_type,
                    "metadata": stat.metadata
                }

        except Exception as e:
            logging.error(f"Stat failed: {e}")
            return {}

    async def check_health(self) -> HealthStatus:
        """检查存储服务健康状态"""
        try:
            if self._client == "backend":
                # 检查backend/file-storage服务
                # health = await backend.file_storage.health()
                # return HealthStatus(
                #     status="healthy" if health.ok else "unhealthy",
                #     message=health.message
                # )
                return HealthStatus(
                    status="unavailable",
                    message="backend/file-storage not implemented"
                )
            else:
                # 检查MinIO服务
                if self.config.bucket:
                    # 单桶模式：检查桶是否存在
                    exists = self._client.bucket_exists(self.config.bucket)
                    if exists:
                        return HealthStatus(
                            status="healthy",
                            message=f"Bucket '{self.config.bucket}' exists"
                        )
                    else:
                        return HealthStatus(
                            status="unhealthy",
                            message=f"Bucket '{self.config.bucket}' does not exist"
                        )
                else:
                    # 多桶模式：检查服务连接
                    self._client.list_buckets()
                    return HealthStatus(
                        status="healthy",
                        message="MinIO service is accessible"
                    )

        except Exception as e:
            logging.error(f"Health check failed: {e}")
            return HealthStatus(
                status="error",
                message=f"Health check failed: {e}"
            )

    async def _reconnect(self):
        """重新连接MinIO服务"""
        try:
            if self._client != "backend" and HAS_MINIO_LIB:
                self._client = Minio(
                    endpoint=self.config.endpoint,
                    access_key=self.config.access_key,
                    secret_key=self.config.secret_key,
                    secure=self.config.secure,
                    region=self.config.region
                )
                logging.info("Reconnected to MinIO")
        except Exception as e:
            logging.error(f"Reconnect failed: {e}")

    def get_storage_mode(self) -> StorageMode:
        """获取存储模式"""
        if self.config.bucket:
            return StorageMode.SINGLE_BUCKET
        else:
            return StorageMode.MULTI_BUCKET