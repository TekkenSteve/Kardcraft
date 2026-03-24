# implementations/parsers/excel.py - Excel文件解析器
"""
Excel文件解析器

支持.xls、.xlsx和.csv文件的解析
"""

import os
import csv
from typing import List
from pathlib import Path

from .base import BaseFileParser
from ...protocols.parsers import ParseResult


class ExcelParser(BaseFileParser):
    """Excel文件解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [".xls", ".xlsx", ".csv"]
        self._parse_method = config.params.get("parse_method", "deepdoc")
        self._output_format = config.params.get("output_format", "html")

    async def parse(self, file_path: str) -> ParseResult:
        """解析Excel文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 检查文件类型
        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type for ExcelParser: {file_ext}")

        # 根据解析方法选择具体实现
        if self._parse_method == "deepdoc":
            return await self._parse_with_deepdoc(file_path)
        elif self._parse_method == "tcadp":
            return await self._parse_with_tcadp(file_path)
        else:
            # 默认使用简单文本提取
            return await self._parse_simple(file_path)

    async def _parse_simple(self, file_path: str) -> ParseResult:
        """简单Excel解析"""
        try:
            file_ext = Path(file_path).suffix.lower()

            if file_ext == ".csv":
                content = await self._parse_csv(file_path)
            else:
                # .xls or .xlsx
                content = await self._parse_excel_fallback(file_path)

            # 创建解析结果
            metadata = self._get_file_metadata(file_path)
            metadata.update({
                "parse_method": "simple",
                "output_format": "text",
                "warning": "Excel parsing requires pandas or openpyxl library"
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
            raise ValueError(f"Simple Excel parsing failed: {e}")

    async def _parse_csv(self, file_path: str) -> str:
        """解析CSV文件"""
        try:
            content_lines = []
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                for row in reader:
                    content_lines.append(", ".join(row))

            return "\n".join(content_lines)
        except Exception:
            # 如果CSV解析失败，尝试直接读取
            return self._read_file_content(file_path)

    async def _parse_excel_fallback(self, file_path: str) -> str:
        """回退Excel解析"""
        # TODO: 使用pandas或openpyxl解析Excel文件
        # 暂时返回简单信息
        return f"Excel file: {Path(file_path).name}\nNote: Excel parsing requires pandas or openpyxl library"

    async def _parse_with_deepdoc(self, file_path: str) -> ParseResult:
        """使用DeepDoc解析Excel"""
        # TODO: 集成DeepDoc解析器
        # 暂时回退到简单解析
        print(f"Warning: DeepDoc Excel parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)

    async def _parse_with_tcadp(self, file_path: str) -> ParseResult:
        """使用TCADP解析Excel"""
        # TODO: 集成TCADP解析器
        # 暂时回退到简单解析
        print(f"Warning: TCADP Excel parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)