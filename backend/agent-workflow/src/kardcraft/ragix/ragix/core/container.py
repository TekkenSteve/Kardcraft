# core/container.py - 依赖注入容器（LightRAG Server Only）
"""
精简版依赖注入容器

仅提供 LightRAG REST 客户端，并通过 LIGHTRAG-WORKSPACE Header 做隔离。
"""

from typing import Dict, Optional

from .config import LightRAGServerConfig
from .lightrag_service import LightRAGRESTClient, LightRAGServiceManager


class RagixContainer:
    def __init__(self, config: Optional[LightRAGServerConfig] = None):
        self.config = config or LightRAGServerConfig()
        self._components: Dict[str, object] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        manager = LightRAGServiceManager(self.config)
        self._register_component("lightrag_service", manager)
        self._initialized = True

    async def shutdown(self) -> None:
        service = self._components.get("lightrag_service")
        if isinstance(service, LightRAGServiceManager):
            await service.shutdown_all()
        self._components.clear()
        self._initialized = False

    def get_component(self, name: str) -> Optional[object]:
        return self._components.get(name)

    def _register_component(self, name: str, component: object) -> None:
        self._components[name] = component
