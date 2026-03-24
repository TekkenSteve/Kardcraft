"""
File Storage gRPC Client

提供与 file-storage 服务交互的工具函数，封装 gRPC 调用细节。
"""

import logging
import os
from typing import List, Dict, Any, Optional, Tuple
import grpc
from dataclasses import dataclass
from datetime import datetime

from .. import file_storage_pb2
from .. import file_storage_pb2_grpc

logger = logging.getLogger(__name__)


@dataclass
class ConversationFileInfo:
    """对话文件信息"""
    file_id: str
    filename: str
    content_type: str
    file_size: int
    storage_key: str
    uploaded_at: datetime
    custom_meta: Dict[str, str]


@dataclass
class FileMetadata:
    """文件元数据"""
    content_type: str
    content_length: int
    etag: str
    last_modified: datetime
    custom_meta: Dict[str, str]


class FileStorageClient:
    """File Storage gRPC 客户端"""
    
    def __init__(self, endpoint: str = "file-storage:50053", timeout: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout

    @staticmethod
    def _to_datetime(ts) -> datetime:
        if ts is None:
            return datetime.utcnow()
        try:
            return ts.ToDatetime()
        except Exception:
            return datetime.utcnow()
    
    async def download_conversation_file(
        self, 
        user_id: str, 
        file_id: str
    ) -> Tuple[bytes, FileMetadata]:
        """
        下载对话文件
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            Tuple[文件内容, 文件元数据]
        """
        try:
            async with grpc.aio.insecure_channel(self.endpoint) as channel:
                stub = file_storage_pb2_grpc.FileStorageServiceStub(channel)

                request = file_storage_pb2.DownloadConversationFileRequest(
                    user_id=user_id,
                    file_id=file_id,
                )

                file_content = bytearray()
                file_metadata: Optional[FileMetadata] = None

                stream = stub.DownloadConversationFile(request, timeout=self.timeout)
                async for response in stream:
                    kind = response.WhichOneof("data")
                    if kind == "metadata":
                        meta = response.metadata
                        file_metadata = FileMetadata(
                            content_type=meta.content_type,
                            content_length=meta.content_length,
                            etag=meta.etag,
                            last_modified=self._to_datetime(meta.last_modified),
                            custom_meta=dict(meta.custom_meta),
                        )
                    elif kind == "chunk":
                        file_content.extend(response.chunk)

                if file_metadata is None:
                    raise ValueError(f"No metadata received for file_id={file_id}")

                return bytes(file_content), file_metadata

        except Exception as e:
            logger.error(f"下载文件失败: file_id={file_id}, error={e}")
            raise
    
    async def get_conversation_files(
        self, 
        user_id: str, 
        session_id: str, 
        conversation_id: str
    ) -> List[ConversationFileInfo]:
        """
        获取对话的所有文件
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            conversation_id: 对话ID
            
        Returns:
            文件信息列表
        """
        try:
            async with grpc.aio.insecure_channel(self.endpoint) as channel:
                stub = file_storage_pb2_grpc.FileStorageServiceStub(channel)

                request = file_storage_pb2.GetConversationFilesRequest(
                    user_id=user_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                )
                response = await stub.GetConversationFiles(request, timeout=self.timeout)

                files: List[ConversationFileInfo] = []
                for file_info in response.files:
                    files.append(
                        ConversationFileInfo(
                            file_id=file_info.file_id,
                            filename=file_info.filename,
                            content_type=file_info.content_type,
                            file_size=file_info.file_size,
                            storage_key=file_info.storage_key,
                            uploaded_at=self._to_datetime(file_info.uploaded_at),
                            custom_meta=dict(file_info.custom_meta),
                        )
                    )
                return files

        except Exception as e:
            logger.error(f"获取对话文件列表失败: user_id={user_id}, session_id={session_id}, conversation_id={conversation_id}, error={e}")
            raise
    
    async def validate_file(
        self, 
        filename: str, 
        content_type: str, 
        file_size: int, 
        file_header: bytes
    ) -> Tuple[bool, str, List[str]]:
        """
        验证文件
        
        Args:
            filename: 文件名
            content_type: 内容类型
            file_size: 文件大小
            file_header: 文件头部字节（用于魔数验证）
            
        Returns:
            Tuple[是否有效, 错误信息, 警告列表]
        """
        try:
            async with grpc.aio.insecure_channel(self.endpoint) as channel:
                stub = file_storage_pb2_grpc.FileStorageServiceStub(channel)

                request = file_storage_pb2.ValidateFileRequest(
                    filename=filename,
                    content_type=content_type,
                    file_size=file_size,
                    file_header=file_header,
                )
                response = await stub.ValidateFile(request, timeout=self.timeout)
                return response.is_valid, response.validation_error, list(response.warnings)

        except Exception as e:
            logger.error(f"文件验证失败: filename={filename}, error={e}")
            raise
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            服务是否健康
        """
        try:
            async with grpc.aio.insecure_channel(self.endpoint) as channel:
                stub = file_storage_pb2_grpc.FileStorageServiceStub(channel)
                response = await stub.GetHealth(file_storage_pb2.HealthRequest(), timeout=5)
                return response.status == "healthy"

        except Exception as e:
            logger.error(f"File-storage 健康检查失败: {e}")
            return False


# 全局客户端实例
_file_storage_client: Optional[FileStorageClient] = None


def get_file_storage_client(endpoint: str = "file-storage:50053") -> FileStorageClient:
    """获取 file-storage 客户端实例"""
    global _file_storage_client
    if _file_storage_client is None:
        resolved_endpoint = os.getenv("FILE_STORAGE_GRPC_ENDPOINT", endpoint)
        _file_storage_client = FileStorageClient(resolved_endpoint)
    return _file_storage_client


# 便捷函数
async def download_conversation_file(user_id: str, file_id: str) -> Tuple[bytes, FileMetadata]:
    """便捷函数：下载对话文件"""
    client = get_file_storage_client()
    return await client.download_conversation_file(user_id, file_id)


async def get_conversation_files(user_id: str, session_id: str, conversation_id: str) -> List[ConversationFileInfo]:
    """便捷函数：获取对话文件列表"""
    client = get_file_storage_client()
    return await client.get_conversation_files(user_id, session_id, conversation_id)


async def validate_file(filename: str, content_type: str, file_size: int, file_header: bytes) -> Tuple[bool, str, List[str]]:
    """便捷函数：验证文件"""
    client = get_file_storage_client()
    return await client.validate_file(filename, content_type, file_size, file_header)


async def check_file_storage_health() -> bool:
    """便捷函数：检查 file-storage 服务健康状态"""
    client = get_file_storage_client()
    return await client.health_check()
