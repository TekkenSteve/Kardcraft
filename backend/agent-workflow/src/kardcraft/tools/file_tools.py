"""
文件处理工具
从 MinIO 读取并处理文件
"""

import asyncio
import io
import logging
import mimetypes
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from ..services.minio_client import get_minio_client

logger = logging.getLogger(__name__)


class FileProcessor:
    """文件处理器"""

    def __init__(self):
        self.minio_client = get_minio_client()

    async def process_files_in_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理输入中的文件

        Args:
            input_data: 包含文件信息的输入数据

        Returns:
            处理后的输入数据，文件内容已加载
        """
        if "files" not in input_data:
            return input_data

        files = input_data["files"]
        if not isinstance(files, list):
            return input_data

        processed_files = []
        for file_info in files:
            if not isinstance(file_info, dict):
                processed_files.append(file_info)
                continue

            # 处理 MinIO URL
            file_url = file_info.get("url", "")
            if file_url.startswith("minio://"):
                try:
                    file_content = await self.minio_client.get_file_from_url(file_url)
                    if file_content:
                        # 解析文件内容
                        processed_file = await self._parse_file_content(
                            file_content,
                            file_info.get("filename", ""),
                            file_info.get("content_type", "")
                        )
                        processed_file.update({
                            "file_id": file_info.get("file_id"),
                            "url": file_url,
                            "size": len(file_content)
                        })
                        processed_files.append(processed_file)
                    else:
                        logger.warning(f"Failed to load file: {file_url}")
                        processed_files.append(file_info)
                except Exception as e:
                    logger.error(f"Error processing file {file_url}: {e}")
                    processed_files.append(file_info)
            else:
                # 非 MinIO URL，保持原样
                processed_files.append(file_info)

        input_data["files"] = processed_files
        input_data["file_contents"] = {
            file.get("file_id"): file.get("content")
            for file in processed_files
            if isinstance(file, dict) and "content" in file
        }

        return input_data

    async def _parse_file_content(
        self,
        file_content: bytes,
        filename: str,
        content_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        解析文件内容

        Args:
            file_content: 文件二进制内容
            filename: 文件名
            content_type: 内容类型

        Returns:
            包含解析后内容的字典
        """
        if not content_type:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        result = {
            "filename": filename,
            "content_type": content_type,
            "size": len(file_content)
        }

        # 根据文件类型解析内容
        if content_type.startswith("text/") or filename.endswith(('.txt', '.md', '.py', '.js', '.json', '.yaml', '.yml')):
            try:
                result["content"] = file_content.decode('utf-8')
                result["format"] = "text"
            except UnicodeDecodeError:
                logger.warning(f"Failed to decode {filename} as UTF-8")
                result["content"] = file_content
                result["format"] = "binary"

        elif content_type == "application/pdf":
            result["format"] = "pdf"
            result["content"] = file_content  # TODO: 使用 pdfminer 等库解析 PDF 内容
            # TODO: 集成 RAG，将 PDF 内容向量化并存储

        elif content_type.startswith("image/"):
            result["format"] = "image"
            result["content"] = file_content  # TODO: 使用 OCR 或视觉模型解析图片内容
            # TODO: 集成 RAG，将图片描述向量化并存储

        elif content_type in ["application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            result["format"] = "doc"
            result["content"] = file_content  # TODO: 使用 python-docx 等库解析 Word 文档

        elif content_type in ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
            result["format"] = "excel"
            result["content"] = file_content  # TODO: 使用 openpyxl 等库解析 Excel

        else:
            result["format"] = "binary"
            result["content"] = file_content

        return result

    async def extract_text_from_files(self, input_data: Dict[str, Any]) -> str:
        """
        从文件中提取文本（用于 RAG）

        Args:
            input_data: 包含文件信息的输入数据

        Returns:
            提取的文本

        TODO: 集成 RAG 服务，将提取的文本向量化并存储到向量数据库
        TODO: 支持 RAGAnything 集成
        """
        if "files" not in input_data:
            return ""

        files = input_data["files"]
        if not isinstance(files, list):
            return ""

        texts = []
        for file_info in files:
            if not isinstance(file_info, dict):
                continue

            # 如果已经有解析的文本内容
            if "content" in file_info and isinstance(file_info["content"], str):
                texts.append(f"=== File: {file_info.get('filename', 'unknown')} ===\n{file_info['content']}")
                # TODO: 将文本分片并插入 RAG 索引
            else:
                # 尝试从 MinIO 获取并解析
                file_url = file_info.get("url", "")
                if file_url.startswith("minio://"):
                    try:
                        file_content = await self.minio_client.get_file_from_url(file_url)
                        if file_content:
                            parsed = await self._parse_file_content(
                                file_content,
                                file_info.get("filename", ""),
                                file_info.get("content_type", "")
                            )
                            if isinstance(parsed.get("content"), str):
                                texts.append(f"=== File: {parsed['filename']} ===\n{parsed['content']}")
                                # TODO: 将文本分片并插入 RAG 索引
                    except Exception as e:
                        logger.warning(f"Failed to extract text from {file_url}: {e}")

        # TODO: 批量插入 RAG 向量数据库
        # rag_client = get_rag_client()
        # for text_chunk in split_text(texts):
        #     rag_client.insert_documents(user_id, [{"content": text_chunk, "metadata": {}}])

        return "\n\n".join(texts)


# 工具函数，供 LangGraph 节点使用
async def process_input_files(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理输入中的文件

    Args:
        input_data: 输入数据

    Returns:
        包含处理后的文件的数据
    """
    processor = FileProcessor()
    return await processor.process_files_in_input(input_data)


async def extract_file_text(input_data: Dict[str, Any]) -> str:
    """
    从文件中提取文本

    Args:
        input_data: 输入数据

    Returns:
        提取的文本
    """
    processor = FileProcessor()
    return await processor.extract_text_from_files(input_data)


async def load_file_from_url(file_url: str) -> Optional[bytes]:
    """
    从 URL 加载文件（支持 minio://）

    Args:
        file_url: 文件 URL

    Returns:
        文件内容
    """
    if not file_url.startswith("minio://"):
        return None

    try:
        client = get_minio_client()
        return await client.get_file_from_url(file_url)
    except Exception as e:
        logger.error(f"Failed to load file from {file_url}: {e}")
        return None
