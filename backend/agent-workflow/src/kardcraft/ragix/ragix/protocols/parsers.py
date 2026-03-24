# protocols/parsers.py - 解析器组件协议
"""
解析器组件协议定义

支持装饰器模式，可动态添加功能而不修改原有代码
"""

from typing import Protocol, runtime_checkable, List, Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC
from .component import Component, ComponentConfig
from .processors_bak import DocumentResult


@dataclass
class ParseResult:
    """解析结果 - 支持上下文感知处理"""
    doc_id: str
    content: str
    metadata: Dict[str, Any]
    multimodal_items: List[Dict[str, Any]]
    content_list: Optional[List[Dict[str, Any]]] = None
    entities: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None
    document_structure: Optional[Any] = None  # DocumentStructure 对象，用于上下文提取

    def __post_init__(self):
        if self.entities is None:
            self.entities = []
        if self.relations is None:
            self.relations = []
        # 注意：document_structure 可以为 None，表示不支持上下文提取


@runtime_checkable
class Parser(Component, Protocol):
    """解析器协议 - 支持装饰器增强"""
    
    async def parse(self, file_path: str) -> ParseResult:
        """解析文件"""
        ...
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        ...


class ParserDecorator(ABC):
    """解析器装饰器基类"""
    
    def __init__(self, parser: Parser):
        self._parser = parser
    
    def get_name(self) -> str:
        return f"decorated_{self._parser.get_name()}"
    
    def get_config(self):
        return self._parser.get_config()
    
    async def initialize(self) -> bool:
        return await self._parser.initialize()
    
    async def shutdown(self) -> None:
        await self._parser.shutdown()
    
    def get_supported_extensions(self) -> List[str]:
        return self._parser.get_supported_extensions()
    
    async def parse(self, file_path: str) -> ParseResult:
        """委托给被装饰的解析器 - 子类可重写添加功能"""
        return await self._parser.parse(file_path)


# 文件类型配置类
@dataclass
class FileTypeConfig:
    """单个文件类型配置 - 类似RAGFlow setups中的配置项"""
    parser_type: str  # "pdf", "docx", "excel", "text", "markdown", "image", "audio", "email", "slides"
    parse_method: str = "default"  # "deepdoc", "mineru", "docling", "vlm", "tcadp", "presentation", "general"
    suffix: List[str] = None  # 文件后缀列表，如[".pdf"], [".doc", ".docx"]
    output_format: str = "text"  # "text", "json", "html", "markdown"
    lang: str = "Chinese"
    llm_id: Optional[str] = None  # 用于VLM或特定解析器
    vlm_name: Optional[str] = None

    def __post_init__(self):
        if self.suffix is None:
            # 根据parser_type设置默认后缀
            if self.parser_type == "pdf":
                self.suffix = [".pdf"]
            elif self.parser_type == "docx":
                self.suffix = [".doc", ".docx"]
            elif self.parser_type == "excel":
                self.suffix = [".xls", ".xlsx", ".csv"]
            elif self.parser_type == "text":
                self.suffix = [".txt"]
            elif self.parser_type == "markdown":
                self.suffix = [".md", ".markdown"]
            elif self.parser_type == "html":
                self.suffix = [".html", ".htm"]
            elif self.parser_type == "json":
                self.suffix = [".json"]
            elif self.parser_type == "image":
                self.suffix = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
            elif self.parser_type == "audio":
                self.suffix = [".wav", ".mp3", ".aac", ".flac", ".ogg"]
            elif self.parser_type == "slides":
                self.suffix = [".pptx"]
            elif self.parser_type == "email":
                self.suffix = [".msg"]
            else:  # 默认或未知类型
                self.suffix = [".txt", ".md"]


# 解析器配置类
@dataclass
class ParserConfig(ComponentConfig):
    """解析器配置"""
    strategy: str = "smart"  # "lightweight", "full", "smart"
    file_size_threshold: int = 10 * 1024 * 1024  # 10MB
    enable_caching: bool = True
    cache_ttl: int = 3600  # 1小时
    enable_multimodal: bool = True
    enable_knowledge_extraction: bool = True
    document_processor: str = "mineru"
    modal_processors: List[str] = None
    file_type_configs: Dict[str, FileTypeConfig] = None  # 文件类型配置字典
    default_parser: str = "smart"  # 默认解析器

    def __post_init__(self):
        if not hasattr(self, 'name') or not self.name:
            self.name = f"parser_{self.strategy}"
        if self.modal_processors is None:
            self.modal_processors = ["image", "table"]
        if self.file_type_configs is None:
            # 设置默认配置，类似RAGFlow的setups
            self.file_type_configs = {
                "pdf": FileTypeConfig(
                    parser_type="pdf",
                    parse_method="deepdoc",
                    suffix=[".pdf"],
                    output_format="json",
                    lang="Chinese"
                ),
                "spreadsheet": FileTypeConfig(
                    parser_type="excel",
                    parse_method="deepdoc",
                    suffix=[".xls", ".xlsx", ".csv"],
                    output_format="html",
                    lang="Chinese"
                ),
                "word": FileTypeConfig(
                    parser_type="docx",
                    parse_method="deepdoc",
                    suffix=[".doc", ".docx"],
                    output_format="json",
                    lang="Chinese"
                ),
                "slides": FileTypeConfig(
                    parser_type="slides",
                    parse_method="presentation",
                    suffix=[".pptx"],
                    output_format="json",
                    lang="Chinese"
                ),
                "markdown": FileTypeConfig(
                    parser_type="markdown",
                    parse_method="general",
                    suffix=[".md", ".markdown"],
                    output_format="json",
                    lang="Chinese"
                ),
                "text": FileTypeConfig(
                    parser_type="text",
                    parse_method="general",
                    suffix=[".txt"],
                    output_format="json",
                    lang="Chinese"
                ),
                "image": FileTypeConfig(
                    parser_type="image",
                    parse_method="vlm",
                    suffix=[".jpg", ".jpeg", ".png", ".gif"],
                    output_format="text",
                    lang="Chinese"
                ),
                "audio": FileTypeConfig(
                    parser_type="audio",
                    parse_method="general",
                    suffix=[".wav", ".mp3", ".aac", ".flac", ".ogg"],
                    output_format="json",
                    lang="Chinese"
                ),
                "email": FileTypeConfig(
                    parser_type="email",
                    parse_method="general",
                    suffix=[".msg"],
                    output_format="json",
                    lang="Chinese"
                )
            }
        super().__post_init__()


@dataclass
class SmartStrategyConfig:
    """智能策略配置"""
    file_size_threshold: int = 10 * 1024 * 1024  # 10MB
    lightweight_extensions: List[str] = None
    full_processing_extensions: List[str] = None
    
    def __post_init__(self):
        if self.lightweight_extensions is None:
            self.lightweight_extensions = [".txt", ".md"]
        if self.full_processing_extensions is None:
            self.full_processing_extensions = [".pdf", ".docx"]


@dataclass
class CacheConfig:
    """缓存配置"""
    enabled: bool = True
    ttl: int = 3600  # 1小时
    max_size: int = 1000  # 最大缓存条目数
    cache_dir: Optional[str] = None
