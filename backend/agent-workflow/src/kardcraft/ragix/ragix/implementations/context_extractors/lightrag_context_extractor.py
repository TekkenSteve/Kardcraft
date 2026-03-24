# implementations/context_extractors/lightrag_context_extractor.py
"""
基于 LightRAG 文档结构的上下文提取器

参考 RAGAnything 的 ContextExtractor 实现，提供基于位置的上下文提取
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from ...protocols.context_extractors import (
    ContextExtractor, ContextExtractionResult, DocumentStructure
)
from ...protocols.component import BaseComponent
from ...protocols.processors_bak import ContextConfig


class LightRAGContextExtractor(BaseComponent):
    """基于 LightRAG 文档结构的上下文提取器

    实现简单的基于位置的上下文提取，适用于大多数文档类型
    """

    def __init__(self, config: ContextConfig):
        """初始化上下文提取器

        Args:
            config: 上下文配置（窗口大小、模式、包含内容等）
        """
        super().__init__(config)
        self.config: ContextConfig = config
        self._tokenizer = None  # 可选：用于 token 计数

    async def _do_initialize(self) -> bool:
        """初始化提取器

        可以在这里初始化分词器等资源
        """
        try:
            # 可以初始化分词器用于 token 计数
            # 但 LightRAGContextExtractor 主要基于位置，所以不需要
            return True
        except Exception as e:
            print(f"Failed to initialize LightRAGContextExtractor: {e}")
            return False

    async def _do_shutdown(self) -> None:
        """关闭提取器"""
        self._tokenizer = None

    async def extract_context_for_element(
        self,
        document_structure: DocumentStructure,
        element_id: str,
        element_index: Optional[int] = None
    ) -> ContextExtractionResult:
        """为指定元素提取上下文"""
        # 查找元素索引
        if element_index is None:
            element_index = document_structure.element_index_map.get(element_id)
            if element_index is None:
                raise ValueError(f"Element {element_id} not found in document structure")

        # 计算上下文窗口
        start_idx, end_idx = self.calculate_context_window(
            element_index,
            len(document_structure.elements),
            self.config.context_mode
        )

        # 提取周围元素
        surrounding_elements = document_structure.elements[start_idx:end_idx + 1]

        # 构建上下文文本（过滤内容类型）
        context_text = self._build_context_text(surrounding_elements)

        return ContextExtractionResult(
            context_text=context_text,
            surrounding_elements=surrounding_elements,
            start_idx=start_idx,
            end_idx=end_idx,
            metadata={
                "element_id": element_id,
                "context_mode": self.config.context_mode,
                "window_size": end_idx - start_idx + 1,
                "window_start": start_idx,
                "window_end": end_idx,
                "total_elements": len(document_structure.elements)
            }
        )

    async def extract_context_with_position(
        self,
        document_structure: DocumentStructure,
        position_info: Dict[str, Any]
    ) -> ContextExtractionResult:
        """基于位置信息提取上下文"""
        element_index = position_info.get("index")
        if element_index is None:
            raise ValueError("Position info must contain 'index' key")

        return await self.extract_context_for_element(
            document_structure,
            f"element_{element_index}",
            element_index
        )

    def calculate_context_window(
        self,
        current_idx: int,
        total_elements: int,
        mode: str = "page"
    ) -> Tuple[int, int]:
        """计算上下文窗口索引范围

        Args:
            current_idx: 当前元素索引
            total_elements: 总元素数量
            mode: 上下文模式 ("page", "chunk", "token")

        Returns:
            (start_idx, end_idx) 索引范围（包含）
        """
        # 基础窗口大小
        window_size = self.config.context_window

        if mode == "page":
            # 页面模式：使用固定窗口大小
            half_window = window_size // 2
            start_idx = max(0, current_idx - half_window)
            end_idx = min(total_elements - 1, current_idx + half_window)

        elif mode == "chunk":
            # 块模式：尝试保持语义连贯性
            # 简单实现：扩展窗口直到达到最大 token 数或遇到边界
            start_idx = max(0, current_idx - window_size)
            end_idx = min(total_elements - 1, current_idx + window_size)

        elif mode == "token":
            # Token 模式：基于 token 计数调整窗口
            # 这里简化实现，使用固定窗口
            start_idx = max(0, current_idx - window_size)
            end_idx = min(total_elements - 1, current_idx + window_size)

        else:
            # 默认使用页面模式
            half_window = window_size // 2
            start_idx = max(0, current_idx - half_window)
            end_idx = min(total_elements - 1, current_idx + half_window)

        # 确保窗口至少包含当前元素
        if start_idx > current_idx:
            start_idx = current_idx
        if end_idx < current_idx:
            end_idx = current_idx

        return start_idx, end_idx

    async def extract_context_batch(
        self,
        document_structure: DocumentStructure,
        element_ids: List[str]
    ) -> List[ContextExtractionResult]:
        """批量提取上下文"""
        results = []
        for element_id in element_ids:
            try:
                result = await self.extract_context_for_element(
                    document_structure, element_id
                )
                results.append(result)
            except Exception as e:
                print(f"Failed to extract context for element {element_id}: {e}")
                # 添加空结果作为占位符
                results.append(ContextExtractionResult(
                    context_text="",
                    surrounding_elements=[],
                    start_idx=0,
                    end_idx=0,
                    metadata={"error": str(e), "element_id": element_id}
                ))

        return results

    def _build_context_text(self, elements: List[Dict[str, Any]]) -> str:
        """构建上下文文本，支持内容过滤

        Args:
            elements: 元素列表

        Returns:
            构建的上下文文本
        """
        text_parts = []

        for elem in elements:
            content_type = elem.get("type", "text")

            # 根据配置过滤内容类型
            if (self.config.filter_content_types and
                content_type not in self.config.filter_content_types):
                continue

            content = elem.get("content", "")
            if not content:
                continue

            # 根据配置包含标题和标题
            if self.config.include_headers and elem.get("is_header", False):
                # 根据标题级别格式化
                header_level = elem.get("header_level", 2)
                prefix = "#" * header_level + " "
                text_parts.append(f"{prefix}{content}")
            elif self.config.include_captions and elem.get("is_caption", False):
                text_parts.append(f"Caption: {content}")
            else:
                text_parts.append(content)

        return "\n".join(text_parts)

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数量（简化实现）"""
        # 简单估算：1 token ≈ 4个英文字符或2个中文字符
        # 实际应用中应使用实际的分词器
        if not text:
            return 0

        # 粗略估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        estimated_tokens = (chinese_chars // 2) + (other_chars // 4)

        return max(1, estimated_tokens)