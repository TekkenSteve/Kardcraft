# protocols/processors.py - 处理器组件协议
"""
处理器组件协议定义

参考 Yuxi-Know/src/plugins/ 和 RAGAnything 的多模态处理器设计
"""

from typing import Protocol, runtime_checkable, List, Dict, Any, Optional
from dataclasses import dataclass
from .component import Component, ComponentConfig, HealthStatus


@dataclass
class DocumentResult:
    """文档处理结果"""
    content: str
    metadata: Dict[str, Any]
    multimodal_items: Optional[List[Dict[str, Any]]] = None
    
    def __post_init__(self):
        if self.multimodal_items is None:
            self.multimodal_items = []


@dataclass
class ModalItem:
    """多模态项目"""
    content_type: str  # "image", "table", "equation", etc.
    content: Any
    metadata: Dict[str, Any]
    item_info: Optional[Dict[str, Any]] = None  # 用于上下文提取
    
    def __post_init__(self):
        if self.item_info is None:
            self.item_info = {}


@dataclass
class ProcessedModalItem:
    """处理后的多模态项目"""
    enhanced_description: str
    entity_info: Dict[str, Any]
    chunk_content: str
    original_item: ModalItem


@runtime_checkable
class DocumentProcessor(Component, Protocol):
    """文档处理器协议 - 参考 BaseDocumentProcessor"""
    
    async def process(self, file_path: str, params: Optional[Dict[str, Any]] = None) -> DocumentResult:
        """处理文档文件"""
        ...
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        ...
    
    def supports_file_type(self, file_extension: str) -> bool:
        """检查是否支持指定文件类型"""
        ...
    
    async def check_health(self) -> HealthStatus:
        """检查处理器健康状态"""
        ...


@runtime_checkable
class ModalProcessor(Component, Protocol):
    """多模态处理器协议 - 参考 RAGAnything 的 modalprocessors"""
    
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """处理多模态项目"""
        ...
    
    def get_supported_types(self) -> List[str]:
        """获取支持的内容类型"""
        ...
    
    def supports_content_type(self, content_type: str) -> bool:
        """检查是否支持指定内容类型"""
        ...
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """仅生成描述，不进行实体关系提取 - 用于批处理第一阶段"""
        ...


# 处理器配置类
@dataclass
class DocumentProcessorConfig(ComponentConfig):
    """文档处理器配置"""
    processor_type: str = "mineru"  # "mineru", "rapid_ocr", "paddlex", etc.
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: int = 300
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    supported_extensions: List[str] = None
    
    def __post_init__(self):
        if not hasattr(self, 'name') or not self.name:
            self.name = f"doc_processor_{self.processor_type}"
        if self.supported_extensions is None:
            self.supported_extensions = [".pdf", ".docx", ".txt", ".md"]
        super().__post_init__()


@dataclass
class ModalProcessorConfig(ComponentConfig):
    """多模态处理器配置 - 支持上下文感知处理"""
    processor_type: str = "image"  # "image", "table", "equation", "generic"
    llm_model: str = "gpt-4o-mini"
    vision_model: Optional[str] = None  # 用于图像处理

    # 上下文提取配置（向后兼容字段）
    context_window: int = 1  # 上下文窗口大小
    context_mode: str = "page"  # "page", "chunk", "token"
    max_context_tokens: int = 2000
    include_headers: bool = True
    include_captions: bool = True

    # 新的上下文感知配置
    context_config: Optional['ContextConfig'] = None  # 完整的上下文配置
    enable_context_extraction: bool = True  # 是否启用了上下文提取
    context_extractor_type: str = "lightrag"  # "lightrag" | "llm_enhanced" | "none"

    supported_types: List[str] = None

    def __post_init__(self):
        if not hasattr(self, 'name') or not self.name:
            self.name = f"modal_processor_{self.processor_type}"

        # 设置支持的类型
        if self.supported_types is None:
            if self.processor_type == "image":
                self.supported_types = ["image"]
            elif self.processor_type == "table":
                self.supported_types = ["table"]
            elif self.processor_type == "equation":
                self.supported_types = ["equation"]
            else:
                self.supported_types = ["generic"]

        # 创建默认的 ContextConfig（如果未提供）
        if self.enable_context_extraction and self.context_config is None:
            self.context_config = ContextConfig(
                context_window=self.context_window,
                context_mode=self.context_mode,
                max_context_tokens=self.max_context_tokens,
                include_headers=self.include_headers,
                include_captions=self.include_captions,
                filter_content_types=["text"]  # 默认只包含文本
            )

        super().__post_init__()


@dataclass
class ContextConfig:
    """上下文提取配置 - 参考 RAGAnything 的 ContextConfig"""
    context_window: int = 1
    context_mode: str = "page"  # "page", "chunk", "token"
    max_context_tokens: int = 2000
    include_headers: bool = True
    include_captions: bool = True
    filter_content_types: List[str] = None
    
    def __post_init__(self):
        if self.filter_content_types is None:
            self.filter_content_types = ["text"]