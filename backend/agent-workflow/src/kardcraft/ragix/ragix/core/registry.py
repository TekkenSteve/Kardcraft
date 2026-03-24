# core/registry.py - 组件注册表
"""
组件注册表

管理所有可插拔组件的注册和发现
"""

from typing import Dict, Type, List, Any, Optional
import os

from ..protocols.component import Component


class ComponentRegistry:
    """组件注册表 - 管理所有可插拔组件"""

    def __init__(self):
        self._components: Dict[str, Dict[str, Type[Component]]] = {
            "models": {},
            "processors": {},
            "parsers": {},
            "retrievers": {},
            "refiners": {},
            "context_extractors": {},
            "storage": {},  # 新增存储类别
        }
        self._instances: Dict[str, Component] = {}

        # 注册默认组件
        self._register_default_components()

    def _register_default_components(self):
        """注册默认组件"""
        # # 注册处理器组件
        # from ..implementations.processors import (
        #     MinerUProcessor,
        #     RapidOCRProcessor,
        #     ImageModalProcessor,
        #     TableModalProcessor,
        #     EquationModalProcessor,
        #     GenericModalProcessor,
        # )

        # self.register_component("processors", "mineru", MinerUProcessor)
        # self.register_component("processors", "rapid_ocr", RapidOCRProcessor)
        # self.register_component("processors", "image", ImageModalProcessor)
        # self.register_component("processors", "table", TableModalProcessor)
        # self.register_component("processors", "equation", EquationModalProcessor)
        # self.register_component("processors", "generic", GenericModalProcessor)

        # 注册解析器组件
        from ..implementations.parsers import (
            PdfParser,
            DocxParser,
            ExcelParser,
            SmartParser,
        )

        self.register_component("parsers", "pdf", PdfParser)
        self.register_component("parsers", "docx", DocxParser)
        self.register_component("parsers", "excel", ExcelParser)
        self.register_component("parsers", "smart", SmartParser)

        # 可选引擎（仅在 .env.ragix 配置时注册）
        if self._is_enabled("RAGIX_ENABLE_MINERU"):
            from ..implementations.parsers.engines.mineru import MinerUParser
            self.register_component("parsers", "mineru", MinerUParser)
        if self._is_enabled("RAGIX_ENABLE_MINERU_API"):
            from ..implementations.parsers.engines.mineru_api import MinerUAPIParser
            self.register_component("parsers", "mineru_api", MinerUAPIParser)
        if self._is_enabled("RAGIX_ENABLE_MINERU_CLOUD_API"):
            from ..implementations.parsers.engines.mineru_cloud_api import (
                MinerUCloudAPIParser,
            )
            self.register_component("parsers", "mineru_cloud_api", MinerUCloudAPIParser)
        if self._is_enabled("RAGIX_ENABLE_PADDLEX"):
            from ..implementations.parsers.engines.paddlex import PaddleXParser
            self.register_component("parsers", "paddlex", PaddleXParser)
        if self._is_enabled("RAGIX_ENABLE_RAPID_OCR"):
            from ..implementations.parsers.engines.rapid_ocr import RapidOCRParser
            self.register_component("parsers", "rapid_ocr", RapidOCRParser)
        if self._is_enabled("RAGIX_ENABLE_DEEPSEEK_OCR"):
            from ..implementations.parsers.engines.deepseek_ocr import DeepSeekOCRParser
            self.register_component("parsers", "deepseek_ocr", DeepSeekOCRParser)

        # 注册检索器组件
        from ..implementations.retrievers import (
            VectorRetrieverStrategy,
            KnowledgeGraphRetrieverStrategy,
            HybridRetrieverStrategy,
        )

        # self.register_component("retrievers", "vector", VectorRetrieverStrategy)
        # self.register_component(
        #     "retrievers", "knowledge_graph", KnowledgeGraphRetrieverStrategy
        # )
        # self.register_component("retrievers", "hybrid", HybridRetrieverStrategy)

        # 注册精炼器组件
        from ..implementations.refiners import WDocRefiner, SimpleRefiner

        self.register_component("refiners", "wdoc", WDocRefiner)
        self.register_component("refiners", "simple", SimpleRefiner)

        # 注册上下文提取器组件
        from ..implementations.context_extractors import (
            LightRAGContextExtractor,
            LLMEnhancedContextExtractor,
        )

        self.register_component(
            "context_extractors", "lightrag", LightRAGContextExtractor
        )
        self.register_component(
            "context_extractors", "llm_enhanced", LLMEnhancedContextExtractor
        )

        # 存储组件注册
        from ..implementations.storage import (
            MinIOStorage,
            # S3Storage, LocalStorage, MemoryStorage
        )

        self.register_component("storage", "minio", MinIOStorage)
        # self.register_component("storage", "s3", S3Storage)
        # self.register_component("storage", "local", LocalStorage)
        # self.register_component("storage", "memory", MemoryStorage)

    def register_component(
        self, category: str, name: str, component_class: Type[Component]
    ):
        """注册组件"""
        if category not in self._components:
            self._components[category] = {}

        self._components[category][name] = component_class

    def _is_enabled(self, key: str) -> bool:
        value = os.getenv(key)
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def get_component_class(
        self, category: str, name: str
    ) -> Optional[Type[Component]]:
        """获取组件类"""
        return self._components.get(category, {}).get(name)

    def list_components(self, category: Optional[str] = None) -> Dict[str, List[str]]:
        """列出组件"""
        if category:
            return {category: list(self._components.get(category, {}).keys())}

        return {cat: list(comps.keys()) for cat, comps in self._components.items()}

    def create_component(self, category: str, name: str, config: Any) -> Component:
        """创建组件实例"""
        component_class = self.get_component_class(category, name)
        if not component_class:
            raise ValueError(f"Component not found: {category}/{name}")

        instance_key = f"{category}_{name}_{id(config)}"

        # 检查是否已有实例（单例模式）
        if instance_key not in self._instances:
            self._instances[instance_key] = component_class(config=config)

        return self._instances[instance_key]

    def clear_instances(self):
        """清除所有实例"""
        self._instances.clear()


# 全局注册表实例
_global_registry = ComponentRegistry()


def get_registry() -> ComponentRegistry:
    """获取全局注册表"""
    return _global_registry


def register_component(category: str, name: str, component_class: Type[Component]):
    """注册组件到全局注册表"""
    _global_registry.register_component(category, name, component_class)
