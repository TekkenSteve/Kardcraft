# implementations/parsers/smart.py - 智能解析器
"""
智能解析器

职责：选择解析策略 + 路由解析器 + 回退
不承载复杂度算法与缓存细节（交给 utils 与调用层）
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

from ...protocols.parsers import Parser, ParserConfig, ParseResult, FileTypeConfig
from ...protocols.component import BaseComponent
from ...utils.content_analyzer import ContentAnalyzer, DocumentComplexity
from kardcraft.utils.logger import logger


class SmartParser(BaseComponent):
    """智能解析器 - 根据文件类型与策略选择解析器"""

    def __init__(self, config: ParserConfig):
        super().__init__(config)
        self.config: ParserConfig = config
        from ...core.registry import get_registry
        self.registry = get_registry()
        self._parsers_cache: Dict[str, Parser] = {}
        self._file_type_map: Dict[str, str] = self._build_file_type_map()
        self._content_analyzer = ContentAnalyzer()

    async def _do_initialize(self) -> bool:
        return True

    async def parse(self, file_path: str) -> ParseResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        strategy = self.choose_parser_strategy(file_path)
        if strategy == "lightrag_native":
            raise ValueError(
                "LightRAG native parsing recommended for this format; "
                "use server-side /documents/upload instead."
            )

        file_ext = Path(file_path).suffix.lower()
        file_type = self._get_file_type(file_ext)
        type_config = self.config.file_type_configs.get(file_type)
        if not type_config:
            return await self._use_default_parser(file_path)

        parser = await self._get_or_create_parser(
            file_path, file_type, type_config, file_ext, strategy
        )
        result = await parser.parse(file_path)

        # 二次判断：Docling 解析的 PDF 若复杂度高，尝试 MinerU
        if strategy == "docling_first" and file_ext == ".pdf":
            analysis = self._content_analyzer.analyze_content(
                result.content_list or [],
                file_path,
            )
            if analysis.complexity in (
                DocumentComplexity.COMPLEX,
                DocumentComplexity.MULTIMODAL_HEAVY,
            ):
                mineru = await self._get_optional_parser("mineru")
                if mineru:
                    logger.info("High multimodal ratio detected. Re-parse PDF with MinerU.")
                    try:
                        return await mineru.parse(file_path)
                    except Exception as e:
                        logger.warning(f"MinerU re-parse failed, fallback to Docling: {e}")

        return result

    def choose_parser_strategy(self, file_path: str) -> str:
        """策略选择（参考 RAG-Anything 原则）"""
        ext = Path(file_path).suffix.lower()
        if ext in {".txt", ".md", ".markdown", ".csv"}:
            return "lightrag_native"
        if ext in {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".tif",
            ".gif",
            ".webp",
        }:
            return "raganything_enhanced"
        if ext in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".html", ".htm"}:
            return "docling_first"
        return "enhanced_parser"

    def get_supported_extensions(self) -> List[str]:
        extensions = []
        for config in self.config.file_type_configs.values():
            extensions.extend(config.suffix)
        return list(set(extensions))

    def _build_file_type_map(self) -> Dict[str, str]:
        file_type_map = {}
        for file_type, config in self.config.file_type_configs.items():
            for suffix in config.suffix:
                file_type_map[suffix] = file_type
        return file_type_map

    def _get_file_type(self, file_ext: str) -> str:
        return self._file_type_map.get(file_ext, "unknown")

    async def _get_or_create_parser(
        self,
        file_path: str,
        file_type: str,
        type_config: FileTypeConfig,
        file_ext: str,
        strategy: str,
    ) -> Parser:
        candidates = self._select_parser_candidates(file_type, type_config, file_ext, strategy)
        for name in candidates:
            parser = await self._get_optional_parser(name, file_type, type_config, file_ext)
            if parser:
                return parser

        default_parser = await self._get_optional_parser(
            self.config.default_parser, file_type, type_config, file_ext
        )
        if default_parser:
            return default_parser

        raise ValueError(f"No available parser for {file_path}")

    def _select_parser_candidates(
        self,
        file_type: str,
        type_config: FileTypeConfig,
        file_ext: str,
        strategy: str,
    ) -> List[str]:
        override = self.config.params.get("parser_override")
        if override:
            if isinstance(override, str):
                return [p.strip() for p in override.split(",") if p.strip()]
            if isinstance(override, list):
                return [str(p).strip() for p in override if str(p).strip()]
        mapped = self._map_parser_name(file_type, type_config, file_ext)
        if strategy == "raganything_enhanced":
            return ["mineru", mapped]
        if strategy == "docling_first":
            return ["docling", mapped]
        return [mapped]

    async def _get_optional_parser(
        self,
        name: str,
        file_type: Optional[str] = None,
        type_config: Optional[FileTypeConfig] = None,
        file_ext: Optional[str] = None,
    ) -> Optional[Parser]:
        cache_key = f"{name}:{file_type}:{getattr(type_config, 'parse_method', 'default')}"
        if cache_key in self._parsers_cache:
            return self._parsers_cache[cache_key]

        parser_class = self.registry.get_component_class("parsers", name)
        if not parser_class:
            return None

        parser_config = ParserConfig(
            name=f"{file_type or name}_{getattr(type_config, 'parse_method', 'default')}",
            params={
                "parse_method": self._resolve_parse_method(name, type_config),
                "output_format": getattr(type_config, "output_format", "text"),
                "lang": getattr(type_config, "lang", "Chinese"),
                "llm_id": getattr(type_config, "llm_id", None),
                "vlm_name": getattr(type_config, "vlm_name", None),
                "file_type": file_type,
                "file_ext": file_ext,
                **(self.config.params.get("parser_params") or {}),
            },
        )

        parser = parser_class(parser_config)
        ok = await parser.initialize()
        if ok:
            self._parsers_cache[cache_key] = parser
            return parser
        return None

    async def _use_default_parser(self, file_path: str) -> ParseResult:
        if self.config.default_parser == "smart":
            raise ValueError("Default parser cannot be SmartParser for unknown types.")
        parser = await self._get_optional_parser(self.config.default_parser)
        if not parser:
            raise ValueError(f"Default parser not found: {self.config.default_parser}")
        return await parser.parse(file_path)

    def _map_parser_name(self, file_type: str, type_config: FileTypeConfig, file_ext: str) -> str:
        if type_config.parser_type != "auto":
            return type_config.parser_type
        if file_type == "pdf":
            if type_config.parse_method == "mineru":
                return "mineru"
            if type_config.parse_method == "mineru_api":
                return "mineru_api"
            if type_config.parse_method in {"mineru_cloud", "mineru_cloud_api"}:
                return "mineru_cloud_api"
            if type_config.parse_method == "docling":
                return "docling"
            return "pdf"
        if file_type == "spreadsheet":
            return "excel"
        if file_type == "word":
            return "docx"
        if file_type == "slides":
            return "slides"
        if file_type == "markdown":
            return "markdown"
        if file_type == "text":
            return "text"
        if file_type == "image":
            return "image"
        if file_type == "audio":
            return "audio"
        if file_type == "email":
            return "email"
        return file_type

    def _resolve_parse_method(
        self, name: str, type_config: Optional[FileTypeConfig]
    ) -> str:
        override = self.config.params.get("parse_method_override")
        if override:
            return str(override)
        if name == "mineru_api":
            return "auto"
        if name == "mineru_cloud_api":
            return "vlm"
        return getattr(type_config, "parse_method", "default")
