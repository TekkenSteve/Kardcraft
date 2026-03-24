# protocols/retrievers.py - 检索器组件协议
"""
检索器组件协议定义

支持策略模式，算法可替换，支持多种检索策略
"""

from typing import Protocol, runtime_checkable, List, Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC
from .component import Component, ComponentConfig
from .._types import Ref


@dataclass
class RetrievalResult:
    """检索结果"""
    text: str
    score: float
    metadata: Dict[str, Any]
    source_id: Optional[str] = None
    
    def to_ref(self) -> Ref:
        """转换为 Ref 对象"""
        return Ref(
            text=self.text,
            metadata=self.metadata,
            score=self.score
        )


@runtime_checkable
class Retriever(Component, Protocol):
    """检索器协议 - 策略模式"""
    
    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """检索相关文档"""
        ...
    
    async def batch_retrieve(
        self, 
        queries: List[str], 
        top_k: int = 10
    ) -> List[List[RetrievalResult]]:
        """批量检索"""
        ...


class RetrieverStrategy(ABC):
    """检索器策略基类"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
    
    def get_name(self) -> str:
        return self.name
    
    def get_config(self) -> Dict[str, Any]:
        return self.config
    
    async def initialize(self) -> bool:
        """初始化策略"""
        return True
    
    async def shutdown(self) -> None:
        """关闭策略"""
        pass
    
    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """检索实现 - 子类必须实现"""
        raise NotImplementedError


class RetrieverDecorator(ABC):
    """检索器装饰器基类"""
    
    def __init__(self, retriever: Retriever):
        self._retriever = retriever
    
    def get_name(self) -> str:
        return f"decorated_{self._retriever.get_name()}"
    
    def get_config(self):
        return self._retriever.get_config()
    
    async def initialize(self) -> bool:
        return await self._retriever.initialize()
    
    async def shutdown(self) -> None:
        await self._retriever.shutdown()
    
    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """委托给被装饰的检索器 - 子类可重写添加功能"""
        return await self._retriever.retrieve(query, top_k)
    
    async def batch_retrieve(
        self, 
        queries: List[str], 
        top_k: int = 10
    ) -> List[List[RetrievalResult]]:
        """批量检索 - 默认实现"""
        results = []
        for query in queries:
            result = await self.retrieve(query, top_k)
            results.append(result)
        return results


# 检索器配置类
@dataclass
class RetrieverConfig(ComponentConfig):
    """检索器配置"""
    top_k: int = 10
    enable_vector: bool = True
    enable_knowledge_graph: bool = True
    enable_hybrid: bool = True
    hybrid_weights: Dict[str, float] = None
    enable_reranking: bool = False
    reranker_model: Optional[str] = None
    
    def __post_init__(self):
        if not hasattr(self, 'name') or not self.name:
            self.name = "retriever"
        if self.hybrid_weights is None:
            self.hybrid_weights = {"vector": 0.6, "kg": 0.4}
        super().__post_init__()


@dataclass
class VectorRetrieverConfig:
    """向量检索器配置"""
    vector_store_type: str = "lightrag"  # "lightrag", "chroma", "qdrant", etc.
    similarity_metric: str = "cosine"
    search_params: Dict[str, Any] = None

    def __post_init__(self):
        if self.search_params is None:
            self.search_params = {}


@dataclass
class KnowledgeGraphConfig:
    """知识图谱检索器配置"""
    graph_store_type: str = "lightrag"  # "lightrag", "neo4j", etc.
    max_hops: int = 2
    entity_weight: float = 0.6
    relation_weight: float = 0.4
    search_params: Dict[str, Any] = None

    def __post_init__(self):
        if self.search_params is None:
            self.search_params = {}


@dataclass
class HybridRetrieverConfig:
    """混合检索器配置"""
    strategy_weights: Dict[str, float] = None
    fusion_method: str = "rrf"  # "rrf", "weighted_sum", "max"
    rrf_k: int = 60  # RRF 参数

    def __post_init__(self):
        if self.strategy_weights is None:
            self.strategy_weights = {"vector": 0.6, "kg": 0.4}
