# implementations/parsers/docx.py - Word文档解析器
"""
Word文档解析器

支持.doc和.docx文件的解析
"""

import os
from typing import List
from pathlib import Path

from .base import BaseFileParser
from ...protocols.parsers import ParseResult


class DocxParser(BaseFileParser):
    """Word文档解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [".doc", ".docx"]
        self._parse_method = config.params.get("parse_method", "deepdoc")
        self._lang = config.params.get("lang", "Chinese")

    async def parse(self, file_path: str) -> ParseResult:
        """解析Word文档"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 检查文件类型
        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type for DocxParser: {file_ext}")

        # 根据解析方法选择具体实现
        if self._parse_method == "deepdoc":
            return await self._parse_with_deepdoc(file_path)
        else:
            # 默认使用简单文本提取
            return await self._parse_simple(file_path)

    async def _parse_simple(self, file_path: str) -> ParseResult:
        """简单Word文档解析"""
        try:
            # TODO: 使用python-docx库解析Word文档
            # 暂时使用文件读取
            content = self._read_file_content(file_path)

            # 创建解析结果
            metadata = self._get_file_metadata(file_path)
            metadata.update({
                "parse_method": "simple",
                "warning": "Word document parsing requires python-docx library"
            })

            doc_id = self._generate_doc_id(file_path, content)
            document_structure = self._build_document_structure(content, metadata)

            return ParseResult(
                doc_id=doc_id,
                content=content,
                metadata=metadata,
                multimodal_items=[],
                entities=[],
                relations=[],
                document_structure=document_structure
            )

        except Exception as e:
            raise ValueError(f"Simple Word parsing failed: {e}")

    async def _parse_with_deepdoc(self, file_path: str) -> ParseResult:
        """使用DeepDoc解析Word文档"""
        # TODO: 集成DeepDoc解析器
        # 暂时回退到简单解析
        print(f"Warning: DeepDoc Word parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)