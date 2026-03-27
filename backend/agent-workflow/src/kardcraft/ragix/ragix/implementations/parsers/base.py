# implementations/parsers/base.py - 基础解析器基类
"""
基础解析器基类

提供通用解析器功能，特定文件类型解析器可以继承此类
"""

import os
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import hashlib

from ...protocols.parsers import Parser, ParserConfig, ParseResult, FileTypeConfig
from ...protocols.component import BaseComponent
from ...protocols.context_extractors import DocumentStructure


class BaseFileParser(BaseComponent):
    """基础文件解析器 - 所有文件类型解析器的基类"""

    def __init__(self, config: ParserConfig):
        super().__init__(config)
        self.config: ParserConfig = config
        self._parse_method = config.params.get("parse_method", "default")
        self._output_format = config.params.get("output_format", "text")
        self._lang = config.params.get("lang", "Chinese")
        self._supported_extensions: List[str] = []

    async def _do_initialize(self) -> bool:
        """初始化解析器 - 子类可重写"""
        # 基础解析器通常不需要特殊初始化
        return True

    async def parse(self, file_path: str) -> ParseResult:
        """Parse file - subclass must implement"""
        raise NotImplementedError("Subclasses must implement parse()")

    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return self._supported_extensions

    def _supports_file_type(self, file_extension: str) -> bool:
        """检查是否支持指定文件类型"""
        return file_extension.lower() in self.get_supported_extensions()

    def _generate_doc_id(self, file_path: str, content: str = "") -> str:
        """生成文档ID"""
        file_stem = Path(file_path).stem
        if content:
            content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
            return f"doc_{file_stem}_{content_hash}"
        else:
            file_stat = os.stat(file_path)
            file_hash = hashlib.md5(f"{file_path}_{file_stat.st_mtime}".encode()).hexdigest()[:8]
            return f"doc_{file_stem}_{file_hash}"

    def _build_document_structure(self, content: str, metadata: Dict[str, Any]) -> DocumentStructure:
        """构建文档结构用于上下文提取

        默认实现：按段落分割
        """
        elements = []

        # 按换行符分割内容
        paragraphs = content.split('\n')
        for idx, paragraph in enumerate(paragraphs):
            if paragraph.strip():  # 跳过空段落
                element = {
                    "id": f"paragraph_{idx}",
                    "content": paragraph.strip(),
                    "type": "text",
                    "position": {
                        "index": idx,
                        "total": len(paragraphs)
                    }
                }

                # 检测标题（简单规则：以 # 开头）
                if paragraph.strip().startswith('#'):
                    element["type"] = "header"
                    # 计算标题级别
                    element["header_level"] = len(paragraph.strip()) - len(paragraph.strip().lstrip('#'))

                elements.append(element)

        # 构建元素索引映射
        element_index_map = {elem["id"]: idx for idx, elem in enumerate(elements)}

        return DocumentStructure(
            elements=elements,
            metadata=metadata,
            element_index_map=element_index_map
        )

    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """获取文件元数据"""
        path = Path(file_path)
        stat = os.stat(file_path)

        return {
            "file_path": str(file_path),
            "file_name": path.name,
            "file_size": stat.st_size,
            "file_extension": path.suffix.lower(),
            "modified_time": stat.st_mtime,
            "parser": self.get_name(),
            "parse_method": self._parse_method,
            "output_format": self._output_format,
            "lang": self._lang
        }

    def _read_file_content(self, file_path: str) -> str:
        """读取文件内容 - 通用方法"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"Failed to read file {file_path}: {e}")

    def _create_parse_result(
        self,
        file_path: str,
        content: str,
        multimodal_items: List[Dict[str, Any]] = None,
        entities: List[Dict[str, Any]] = None,
        relations: List[Dict[str, Any]] = None,
        content_list: Optional[List[Dict[str, Any]]] = None,
    ) -> ParseResult:
        """创建解析结果对象"""
        metadata = self._get_file_metadata(file_path)
        doc_id = self._generate_doc_id(file_path, content)
        document_structure = self._build_document_structure(content, metadata)

        return ParseResult(
            doc_id=doc_id,
            content=content,
            metadata=metadata,
            multimodal_items=multimodal_items or [],
            content_list=content_list,
            entities=entities or [],
            relations=relations or [],
            document_structure=document_structure
        )
