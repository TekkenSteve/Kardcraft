"""
MinIO 服务客户端
"""

import asyncio
import io
import logging
from typing import Optional, BinaryIO
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinIOClient:
    """MinIO 客户端封装"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        region: str = "us-east-1"
    ):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self.region = region
        self.client: Optional[Minio] = None

    async def connect(self):
        """连接到 MinIO"""
        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                region=self.region
            )
            logger.info(f"MinIO client connected to {self.endpoint}")
        except Exception as e:
            logger.error(f"Failed to connect to MinIO: {e}")
            raise

    async def close(self):
        """关闭连接"""
        self.client = None
        logger.info("MinIO client closed")

    async def get_file(self, bucket: str, object_name: str) -> Optional[bytes]:
        """
        从 MinIO 获取文件

        Args:
            bucket: 存储桶名称
            object_name: 对象名称

        Returns:
            文件内容或 None
        """
        if not self.client:
            raise RuntimeError("MinIO client not connected")

        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.warning(f"Object not found: {bucket}/{object_name}")
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get file from MinIO: {e}")
            raise

    async def put_file(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream"
    ) -> bool:
        """
        上传文件到 MinIO

        Args:
            bucket: 存储桶名称
            object_name: 对象名称
            data: 文件数据
            content_type: 内容类型

        Returns:
            是否成功
        """
        if not self.client:
            raise RuntimeError("MinIO client not connected")

        try:
            data_stream = io.BytesIO(data)
            file_size = len(data)

            self.client.put_object(
                bucket,
                object_name,
                data_stream,
                length=file_size,
                content_type=content_type
            )
            logger.info(f"File uploaded to MinIO: {bucket}/{object_name} ({file_size} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to upload file to MinIO: {e}")
            return False

    async def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires: int = 3600,
    ) -> Optional[str]:
        """
        获取预签名 URL

        Args:
            bucket: 存储桶名称
            object_name: 对象名称
            expires: 过期时间（秒）

        Returns:
            预签名 URL
        """
        if not self.client:
            raise RuntimeError("MinIO client not connected")

        try:
            from datetime import timedelta

            url = self.client.presigned_get_object(
                bucket, object_name, timedelta(seconds=expires)
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None

    async def get_file_metadata(self, bucket: str, object_name: str) -> Optional[dict]:
        """
        获取文件元数据

        Args:
            bucket: 存储桶名称
            object_name: 对象名称

        Returns:
            元数据字典
        """
        if not self.client:
            raise RuntimeError("MinIO client not connected")

        try:
            stat = self.client.stat_object(bucket, object_name)
            return {
                "size": stat.size,
                "etag": stat.etag,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified.isoformat() if hasattr(stat.last_modified, 'isoformat') else str(stat.last_modified),
                "metadata": stat.metadata
            }
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get file metadata: {e}")
            return None

    async def parse_minio_url(self, url: str) -> tuple[str, str]:
        """
        解析 MinIO URL

        Args:
            url: MinIO URL (格式: minio://bucket/object)

        Returns:
            (bucket, object_name)
        """
        parsed = urlparse(url)
        if parsed.scheme != "minio":
            raise ValueError(f"Invalid MinIO URL scheme: {parsed.scheme}")

        bucket = parsed.netloc
        object_name = parsed.path.lstrip('/')

        if not bucket or not object_name:
            raise ValueError(f"Invalid MinIO URL: {url}")

        return bucket, object_name

    async def get_file_from_url(self, url: str) -> Optional[bytes]:
        """
        从 MinIO URL 获取文件

        Args:
            url: MinIO URL

        Returns:
            文件内容
        """
        bucket, object_name = await self.parse_minio_url(url)
        return await self.get_file(bucket, object_name)


# 全局 MinIO 客户端实例
_minio_client: Optional[MinIOClient] = None


def get_minio_client() -> MinIOClient:
    """获取全局 MinIO 客户端实例"""
    global _minio_client
    if _minio_client is None:
        raise RuntimeError("MinIO client not initialized. Call init_minio_client first.")
    return _minio_client


async def init_minio_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
    region: str = "us-east-1"
) -> MinIOClient:
    """初始化 MinIO 客户端"""
    global _minio_client
    _minio_client = MinIOClient(endpoint, access_key, secret_key, secure, region)
    await _minio_client.connect()
    return _minio_client
