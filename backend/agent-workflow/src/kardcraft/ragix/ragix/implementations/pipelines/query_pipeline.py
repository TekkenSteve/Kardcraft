# implementations/pipelines/query_pipeline.py
"""
Query pipeline (LightRAG Server mode).

Base version:
- Single call to LightRAG /query
- Standardizes response into Answer
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Iterable

from ..._types import Answer, Ref
from ...core.lightrag_service import LightRAGRESTClient


@dataclass
class QueryPipelineConfig:
    default_mode: str = "mix"
    multi_mode: str = "mix"
    top_k: int = 10
    include_references: bool = True
    include_chunk_content: bool = False
    enable_rerank: bool = True


class QueryPipeline:
    """Query pipeline wrapper around LightRAG REST client."""

    def __init__(self, config: QueryPipelineConfig):
        self.config = config
        self._server_rerank_enabled: Optional[bool] = None

    async def _detect_rerank_enabled(self, client: LightRAGRESTClient) -> Optional[bool]:
        if self._server_rerank_enabled is not None:
            return self._server_rerank_enabled
        try:
            health = await client.get_health()
            enabled = (
                health.get("configuration", {})
                .get("enable_rerank")
            )
            if isinstance(enabled, bool):
                self._server_rerank_enabled = enabled
                return enabled
        except Exception:
            return None
        return None

    async def query(
        self,
        client: LightRAGRESTClient,
        question: str,
        *,
        session_id: Optional[str],
        mode: Optional[str] = None,
        modes: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        include_references: Optional[bool] = None,
        include_chunk_content: Optional[bool] = None,
        enable_rerank: Optional[bool] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Answer:
        if modes and len(modes) > 1:
            return await self._query_multi(
                client,
                question,
                session_id=session_id,
                modes=modes,
                top_k=top_k,
                include_references=include_references,
                include_chunk_content=include_chunk_content,
                enable_rerank=enable_rerank,
                conversation_history=conversation_history,
            )

        effective_rerank = enable_rerank
        if effective_rerank is None:
            detected = await self._detect_rerank_enabled(client)
            if detected is not None:
                effective_rerank = detected

        result = await client.query(
            question,
            workspace=session_id,
            mode=mode or self.config.default_mode,
            top_k=top_k if top_k is not None else self.config.top_k,
            include_references=(
                include_references
                if include_references is not None
                else self.config.include_references
            ),
            include_chunk_content=(
                include_chunk_content
                if include_chunk_content is not None
                else self.config.include_chunk_content
            ),
            enable_rerank=effective_rerank,
            conversation_history=conversation_history,
        )

        text = result.get("response", "")
        citations = []
        for ref in result.get("references", []) or []:
            citations.append(
                Ref(
                    text=ref.get("file_path") or ref.get("reference_id") or "",
                    metadata=ref,
                    score=1.0,
                )
            )
        return Answer(text=text, citations=citations)

    async def _query_multi(
        self,
        client: LightRAGRESTClient,
        question: str,
        *,
        session_id: Optional[str],
        modes: List[str],
        top_k: Optional[int],
        include_references: Optional[bool],
        include_chunk_content: Optional[bool],
        enable_rerank: Optional[bool],
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> Answer:
        effective_rerank = enable_rerank
        if effective_rerank is None:
            detected = await self._detect_rerank_enabled(client)
            if detected is not None:
                effective_rerank = detected

        async def _run_mode(mode: str) -> Dict[str, Any]:
            return await client.query(
                question,
                workspace=session_id,
                mode=mode,
                top_k=top_k if top_k is not None else self.config.top_k,
                include_references=(
                    include_references
                    if include_references is not None
                    else self.config.include_references
                ),
                include_chunk_content=(
                    include_chunk_content
                    if include_chunk_content is not None
                    else self.config.include_chunk_content
                ),
                enable_rerank=effective_rerank,
                conversation_history=conversation_history,
            )

        tasks = [asyncio.create_task(_run_mode(m)) for m in modes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        mode_results: Dict[str, Dict[str, Any]] = {}
        for mode, result in zip(modes, results):
            if isinstance(result, Exception):
                continue
            mode_results[mode] = result

        if not mode_results:
            return Answer(text="", citations=[])

        primary_mode = (
            self.config.multi_mode
            if self.config.multi_mode in mode_results
            else next(iter(mode_results.keys()))
        )
        primary_result = mode_results[primary_mode]

        citations = self._merge_references(mode_results, primary_mode)
        text = primary_result.get("response", "")
        return Answer(text=text, citations=citations)

    def _merge_references(
        self,
        mode_results: Dict[str, Dict[str, Any]],
        primary_mode: str,
    ) -> List[Ref]:
        seen = set()
        merged: List[Ref] = []
        ordered_modes: Iterable[str] = [primary_mode] + [
            m for m in mode_results.keys() if m != primary_mode
        ]
        for mode in ordered_modes:
            for ref in mode_results.get(mode, {}).get("references", []) or []:
                key = ref.get("file_path") or ref.get("reference_id") or str(ref)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(
                    Ref(
                        text=ref.get("file_path") or ref.get("reference_id") or "",
                        metadata={"mode": mode, **ref},
                        score=1.0,
                    )
                )
        return merged
