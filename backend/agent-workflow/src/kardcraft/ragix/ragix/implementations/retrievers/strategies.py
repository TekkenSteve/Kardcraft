# implementations/retrievers/strategies.py - 检索器策略实现
"""
检索器策略实现

支持 Milvus 向量检索和 Neo4j 知识图谱检索
"""

import asyncio
from typing import List, Dict, Any, Optional, Callable

from ...protocols.retrievers import (
    RetrieverStrategy,
    RetrievalResult,
    VectorRetrieverConfig,
    KnowledgeGraphConfig,
    HybridRetrieverConfig,
)
from kardcraft.utils.logger import logger


class VectorRetrieverStrategy(RetrieverStrategy):
    """向量检索策略 - 支持 LightRAG"""

    def __init__(
        self,
        name: str,
        config: VectorRetrieverConfig,
        vector_store: Any = None,  # LightRAG instance
        embedding_func: Callable = None,
    ):
        super().__init__(name, config.__dict__)
        self.config = config
        self.vector_store = vector_store
        self.embedding_func = embedding_func
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化向量存储"""
        try:
            if self.vector_store:
                self._initialized = True
                logger.info(f"Vector retriever initialized with LightRAG")
                return True

            logger.warning("Vector store not available, using fallback")
            return False

        except Exception as e:
            logger.error(f"Failed to initialize vector retriever: {e}")
            return False

    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """向量检索实现 - 使用 LightRAG"""
        try:
            if self._initialized and self.vector_store:
                from lightrag import QueryParam

                param = QueryParam(mode="local", top_k=top_k)
                results = await self.vector_store.aquery(query, param=param)

                return [
                    RetrievalResult(
                        text=str(r),
                        score=1.0,
                        metadata={
                            "source": "lightrag",
                            "retriever": self.name,
                        },
                        source_id="",
                    )
                    for r in ([results] if isinstance(results, str) else results)
                ]
            else:
                logger.warning("Vector store not initialized, returning empty results")
                return []

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return []


class KnowledgeGraphRetrieverStrategy(RetrieverStrategy):
    """知识图谱检索策略 - 支持 LightRAG"""

    def __init__(
        self,
        name: str,
        config: KnowledgeGraphConfig,
        graph_store: Any = None,  # LightRAG instance
    ):
        super().__init__(name, config.__dict__)
        self.config = config
        self.graph_store = graph_store
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化图存储"""
        try:
            if self.graph_store:
                self._initialized = True
                logger.info(f"Knowledge graph retriever initialized with LightRAG")
                return True

            logger.warning("Graph store not available")
            return False

        except Exception as e:
            logger.error(f"Failed to initialize knowledge graph retriever: {e}")
            return False

    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """知识图谱检索实现 - 使用 LightRAG global 模式"""
        try:
            if self._initialized and self.graph_store:
                from lightrag import QueryParam

                param = QueryParam(mode="global", top_k=top_k)
                results = await self.graph_store.aquery(query, param=param)

                return [
                    RetrievalResult(
                        text=str(r),
                        score=0.9,
                        metadata={
                            "source": "lightrag_kg",
                            "type": "knowledge_graph",
                            "retriever": self.name,
                        },
                        source_id="",
                    )
                    for r in ([results] if isinstance(results, str) else results)
                ]
            else:
                logger.warning("Graph store not initialized, returning empty results")
                return []

        except Exception as e:
            logger.error(f"Knowledge graph retrieval failed: {e}")
            return []


class HybridRetrieverStrategy(RetrieverStrategy):
    """混合检索策略 - 组合多个策略"""

    def __init__(
        self,
        name: str,
        config: HybridRetrieverConfig,
        strategies: List[RetrieverStrategy],
    ):
        super().__init__(name, config.__dict__)
        self.config = config
        self.strategies = strategies
        self.weights = config.strategy_weights

    async def initialize(self) -> bool:
        """初始化所有策略"""
        try:
            for strategy in self.strategies:
                success = await strategy.initialize()
                if not success:
                    logger.warning(f"Failed to initialize strategy: {strategy.name}")
            return True  # 允许部分失败
        except Exception as e:
            logger.error(f"Failed to initialize hybrid retriever: {e}")
            return False

    async def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """混合检索实现"""
        try:
            # 并发执行所有策略
            tasks = [
                strategy.retrieve(query, top_k * 2) for strategy in self.strategies
            ]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)  # type: ignore[assignment]

            # 处理结果
            all_results: List[RetrievalResult] = []
            for i, results in enumerate(results_list):
                if isinstance(results, Exception):
                    logger.error(
                        f"Strategy {self.strategies[i].name} failed: {results}"
                    )
                    continue

                # Skip non-list results
                if not isinstance(results, list):
                    continue

                strategy_name = self.strategies[i].name
                weight = self.weights.get(strategy_name, 1.0)

                # 应用权重
                for result in results:
                    result.score *= weight
                    result.metadata["strategy"] = strategy_name
                    result.metadata["weight"] = weight

                all_results.extend(results)

            # 融合结果
            fused_results = self._fuse_results(all_results)

            return fused_results[:top_k]

        except Exception as e:
            logger.error(f"Hybrid retrieval failed: {e}")
            return []

    def _fuse_results(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """融合结果"""
        if not results:
            return []

        # 去重
        seen_texts = set()
        unique_results = []

        for result in results:
            if result.text not in seen_texts:
                seen_texts.add(result.text)
                unique_results.append(result)

        # 融合方法
        if self.config.fusion_method == "rrf":
            return self._reciprocal_rank_fusion(unique_results)
        elif self.config.fusion_method == "weighted_sum":
            return self._weighted_sum_fusion(unique_results)
        elif self.config.fusion_method == "max":
            return self._max_fusion(unique_results)
        else:
            return sorted(unique_results, key=lambda x: x.score, reverse=True)

    def _reciprocal_rank_fusion(
        self, results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """倒数排名融合"""
        strategy_results = {}
        for result in results:
            strategy = result.metadata.get("strategy", "unknown")
            if strategy not in strategy_results:
                strategy_results[strategy] = []
            strategy_results[strategy].append(result)

        text_to_rrf_score = {}

        for strategy, strategy_res in strategy_results.items():
            sorted_results = sorted(strategy_res, key=lambda x: x.score, reverse=True)

            for rank, result in enumerate(sorted_results):
                rrf_score = 1.0 / (self.config.rrf_k + rank + 1)

                if result.text not in text_to_rrf_score:
                    text_to_rrf_score[result.text] = {"score": 0, "result": result}

                text_to_rrf_score[result.text]["score"] += rrf_score

        rrf_results = []
        for text, data in text_to_rrf_score.items():
            result = data["result"]
            result.score = data["score"]
            result.metadata["rrf_score"] = data["score"]
            rrf_results.append(result)

        return sorted(rrf_results, key=lambda x: x.score, reverse=True)

    def _weighted_sum_fusion(
        self, results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """加权求和"""
        return sorted(results, key=lambda x: x.score, reverse=True)

    def _max_fusion(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """最大值融合"""
        text_to_max_result = {}

        for result in results:
            if result.text not in text_to_max_result:
                text_to_max_result[result.text] = result
            elif result.score > text_to_max_result[result.text].score:
                text_to_max_result[result.text] = result

        max_results = list(text_to_max_result.values())
        return sorted(max_results, key=lambda x: x.score, reverse=True)
