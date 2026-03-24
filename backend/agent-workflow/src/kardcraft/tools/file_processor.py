"""
文件处理工具

负责从 file-storage 服务下载文件并调用 rust 服务解析文档内容。
"""

import logging
from typing import List, Dict, Any, Optional

from ..utils.file_storage_client import download_conversation_file, FileMetadata
from ..utils.document_parser import parse_document

logger = logging.getLogger(__name__)


class FileProcessor:
    """文件处理器"""
    
    def __init__(self):
        pass
    
    async def process_conversation_files(
        self, 
        workspace: Any,
        file_ids: List[str],
        owner: str,
    ) -> List[Dict[str, Any]]:
        """处理对话中的文件列表"""
        if not file_ids:
            return []
        
        logger.info(f"开始处理 {len(file_ids)} 个文件 for owner={owner}")
        
        processed_files = []
        for file_id in file_ids:
            try:
                processed_file = await self.process_single_file(workspace, file_id, owner)
                processed_files.append(processed_file)
                logger.info(f"文件处理成功: {file_id}")
            except Exception as e:
                logger.error(f"文件处理失败: {file_id}, 错误: {e}")
                # 创建错误占位符，不中断整个流程
                processed_files.append({
                    "file_id": file_id,
                    "filename": f"error_{file_id}",
                    "content": f"文件处理失败: {str(e)}",
                    "error": str(e),
                    "metadata": {
                        "content_type": "error",
                        "file_size": 0
                    }
                })
        
        logger.info(f"文件处理完成，成功: {len([f for f in processed_files if 'error' not in f])}, "
                   f"失败: {len([f for f in processed_files if 'error' in f])}")
        
        return processed_files
    
    async def process_single_file(
        self, 
        workspace: Any,
        file_id: str,
        owner: str,
    ) -> Dict[str, Any]:
        """处理单个文件"""
        logger.debug(f"开始处理文件: {file_id} for owner={owner}")
        
        # 1. 使用工具函数从 file-storage 下载文件
        file_content, file_metadata = await download_conversation_file(
            owner, file_id
        )
        
        # 2. 使用工具函数调用 rust 服务解析文档
        parsed_content = await parse_document(
            content=file_content,
            filename=file_metadata.custom_meta.get("original_filename", f"file_{file_id}"),
            content_type=file_metadata.content_type
        )
        
        # 3. 返回处理结果
        return {
            "file_id": file_id,
            "filename": file_metadata.custom_meta.get("original_filename", f"file_{file_id}"),
            "content": parsed_content.get("text", ""),
            "metadata": {
                "content_type": file_metadata.content_type,
                "file_size": file_metadata.content_length,
                "pages": parsed_content.get("pages", 0),
                "language": parsed_content.get("language", "unknown"),
                "success": parsed_content.get("success", False),
                "parser_error": parsed_content.get("error")
            }
        }


# 全局文件处理器实例
_file_processor: Optional[FileProcessor] = None


def get_file_processor() -> FileProcessor:
    """获取文件处理器实例"""
    global _file_processor
    if _file_processor is None:
        _file_processor = FileProcessor()
    return _file_processor


async def process_user_files(
    workspace: Any,
    file_ids: List[str],
    owner: str,
) -> List[Dict[str, Any]]:
    """便捷函数：处理用户文件"""
    if not file_ids:
        return []
    
    processor = get_file_processor()
    return await processor.process_conversation_files(workspace, file_ids, owner)
