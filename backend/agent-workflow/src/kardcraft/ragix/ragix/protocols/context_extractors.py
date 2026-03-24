# protocols/context_extractors.py - 上下文提取器协议
"""
上下文提取器组件协议

参考 RAGAnything 的 ContextExtractor 设计，提供文档上下文提取能力
"""

from typing import Protocol, runtime_checkable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from .component import Component, ComponentConfig
from .processors_bak import ContextConfig


@dataclass
class DocumentStructure:
    """文档结构表示 - 用于上下文提取

    包含文档元素的顺序列表，每个元素都有位置和类型信息
    参考 RAGAnything 的 MinerU 解析结果结构
    """
    elements: List[Dict[str, Any]]  # 文档元素列表，每个元素有位置、类型、内容等信息
    metadata: Dict[str, Any]        # 文档元数据（文件路径、大小、解析器等）
    element_index_map: Dict[str, int]  # 元素ID到索引的映射，用于快速查找


@dataclass
class ContextExtractionResult:
    """上下文提取结果"""
    context_text: str                     # 提取的上下文文本（可用于多模态处理）
    surrounding_elements: List[Dict[str, Any]]  # 周围的原始元素（包含目标元素）
    start_idx: int                        # 起始元素索引（包含）
    end_idx: int                          # 结束元素索引（包含）
    metadata: Dict[str, Any]              # 提取元数据（模式、窗口大小等）


@runtime_checkable
class ContextExtractor(Component, Protocol):
    """上下文提取器协议 - 参考 RAGAnything 的 ContextExtractor

    为多模态处理器提供周围文本上下文，增强图像/表格/公式的理解
    """

    def __init__(self, config: ContextConfig):
        """初始化上下文提取器

        Args:
            config: 上下文配置（窗口大小、模式、包含内容等）
        """
        ...

    async def extract_context_for_element(
        self,
        document_structure: DocumentStructure,
        element_id: str,
        element_index: Optional[int] = None
    ) -> ContextExtractionResult:
        """为指定元素提取上下文

        Args:
            document_structure: 文档结构对象
            element_id: 元素标识符
            element_index: 元素索引（可选，用于性能优化）

        Returns:
            上下文提取结果，包含周围文本和元素信息
        """
        ...

    async def extract_context_with_position(
        self,
        document_structure: DocumentStructure,
        position_info: Dict[str, Any]
    ) -> ContextExtractionResult:
        """基于位置信息提取上下文

        Args:
            document_structure: 文档结构对象
            position_info: 位置信息字典，包含：
                - index: 元素索引
                - page: 页码（如果可用）
                - section: 章节信息（如果可用）

        Returns:
            上下文提取结果
        """
        ...

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
        ...

    async def extract_context_batch(
        self,
        document_structure: DocumentStructure,
        element_ids: List[str]
    ) -> List[ContextExtractionResult]:
        """批量提取上下文

        Args:
            document_structure: 文档结构对象
            element_ids: 元素ID列表

        Returns:
            上下文提取结果列表
        """
        ...


@dataclass
class ContextExtractorConfig(ComponentConfig):
    """上下文提取器配置 - 扩展 ComponentConfig

    用于容器创建上下文提取器实例
    """
    extractor_type: str = "lightrag"  # "lightrag", "llm_enhanced", "rule_based"
    context_config: Optional['ContextConfig'] = None

    def __post_init__(self):
        """后初始化处理"""
        if not hasattr(self, 'name') or not self.name:
            self.name = f"context_extractor_{self.extractor_type}"
        if self.context_config is None:
            from .processors_bak import ContextConfig
            self.context_config = ContextConfig()
        super().__post_init__()