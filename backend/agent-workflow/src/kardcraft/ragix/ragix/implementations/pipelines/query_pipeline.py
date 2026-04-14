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
from ..query_rewrite import QueryRewriter, QueryRewriteConfig, QueryRewriteResult
from kardcraft.utils.logger import logger


@dataclass
class QueryPipelineConfig:
    default_mode: str = "mix"
    multi_mode: str = "mix"
    top_k: int = 10
    include_references: bool = True
    include_chunk_content: bool = False
    enable_rerank: bool = True
    enable_query_rewrite: bool = True


class QueryPipeline:
    """Query pipeline wrapper around LightRAG REST client."""

    def __init__(self, config: QueryPipelineConfig):
        self.config = config
        self._server_rerank_enabled: Optional[bool] = None
        self._rewriter = QueryRewriter(QueryRewriteConfig(enabled=self.config.enable_query_rewrite))

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
        rewrite_hints: Optional[Dict[str, Any]] = None,
    ) -> Answer:
        self._log_history_context(
            session_id=session_id,
            conversation_history=conversation_history,
            phase="query",
        )
        hints = {"workspace": session_id or "default"}
        if rewrite_hints:
            hints.update(rewrite_hints)
        effective_mode = str(mode or self.config.default_mode or "mix").strip().lower()
        if effective_mode == "bypass":
            rewrite = QueryRewriteResult(
                query_type="plain",
                confidence=1.0,
                rewrite_confidence=1.0,
                canonical_query=question,
                retrieval_queries=[question],
                sub_queries=[],
                preserved_intent=question,
                language_hint="",
            )
            effective_question = question
        else:
            rewrite = await self._rewriter.rewrite(
                question,
                conversation_history=conversation_history,
                hints=hints,
            )
            self._log_rewrite_decision(question=question, rewrite=rewrite, session_id=session_id)
            effective_question = rewrite.canonical_query or question
        # "bypass" is a sentinel for skipping rewrite, not a LightRAG query mode.
        query_mode = None if effective_mode == "bypass" else effective_mode

        if rewrite.sub_queries and not (modes and len(modes) > 1):
            return await self._query_multi_intent(
                client=client,
                sub_queries=rewrite.sub_queries,
                session_id=session_id,
                mode=query_mode,
                top_k=top_k,
                include_references=include_references,
                include_chunk_content=include_chunk_content,
                enable_rerank=enable_rerank,
                conversation_history=conversation_history,
            )

        if modes and len(modes) > 1:
            return await self._query_multi(
                client,
                effective_question,
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

        result = await self._run_single_query(
            client=client,
            question=effective_question,
            session_id=session_id,
            mode=query_mode,
            top_k=top_k,
            include_references=include_references,
            include_chunk_content=include_chunk_content,
            effective_rerank=effective_rerank,
            conversation_history=conversation_history,
        )
        self._log_retrieval_hit(
            session_id=session_id,
            query=effective_question,
            result=result,
            path="single",
            query_type=rewrite.query_type,
        )
        return self._answer_from_query_result(result)

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
        self._log_mode_retrieval_hit(
            session_id=session_id,
            query=question,
            mode_results=mode_results,
            primary_mode=primary_mode,
        )
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

    async def _run_single_query(
        self,
        *,
        client: LightRAGRESTClient,
        question: str,
        session_id: Optional[str],
        mode: Optional[str],
        top_k: Optional[int],
        include_references: Optional[bool],
        include_chunk_content: Optional[bool],
        effective_rerank: Optional[bool],
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        resolved_mode = str(mode or self.config.default_mode or "mix").strip().lower()
        if resolved_mode == "bypass":
            resolved_mode = "mix"
        return await client.query(
            question,
            workspace=session_id,
            mode=resolved_mode,
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

    def _answer_from_query_result(self, result: Dict[str, Any]) -> Answer:
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

    async def _query_multi_intent(
        self,
        *,
        client: LightRAGRESTClient,
        sub_queries: List[str],
        session_id: Optional[str],
        mode: Optional[str],
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

        async def _run_one(index: int, q: str) -> tuple[int, str, Dict[str, Any]]:
            try:
                result = await self._run_single_query(
                    client=client,
                    question=q,
                    session_id=session_id,
                    mode=mode,
                    top_k=top_k,
                    include_references=include_references,
                    include_chunk_content=include_chunk_content,
                    effective_rerank=effective_rerank,
                    conversation_history=conversation_history,
                )
                return index, q, result
            except Exception as exc:
                logger.warning("multi-intent sub-query failed", index=index, error=str(exc))
                return index, q, {}

        tasks = [asyncio.create_task(_run_one(i, q)) for i, q in enumerate(sub_queries)]
        items = await asyncio.gather(*tasks)
        items.sort(key=lambda item: item[0])

        merged_sections: List[str] = []
        ref_map: Dict[str, Ref] = {}
        for _, sub_query, result in items:
            response_text = str(result.get("response", "") or "").strip()
            self._log_retrieval_hit(
                session_id=session_id,
                query=sub_query,
                result=result,
                path="multi_intent",
                query_type="multi_intent",
            )
            if response_text:
                merged_sections.append(self._format_multi_intent_section(sub_query, response_text))
            for ref in result.get("references", []) or []:
                key = str(ref.get("file_path") or ref.get("reference_id") or f"{sub_query}:{ref}")
                if key in ref_map:
                    continue
                ref_map[key] = Ref(
                    text=ref.get("file_path") or ref.get("reference_id") or "",
                    metadata={"sub_query": sub_query, **ref},
                    score=1.0,
                )

        merged_text = self._format_multi_intent_answer(merged_sections)
        return Answer(text=merged_text, citations=list(ref_map.values()))

    @staticmethod
    def _history_preview(
        conversation_history: Optional[List[Dict[str, str]]],
        *,
        max_items: int = 8,
        max_chars: int = 200,
    ) -> List[Dict[str, Any]]:
        history = list(conversation_history or [])
        start = max(0, len(history) - max_items)
        preview: List[Dict[str, Any]] = []
        for idx, item in enumerate(history[start:], start=start):
            if not isinstance(item, dict):
                preview.append({"index": idx, "role": "unknown", "content_preview": str(item)[:max_chars]})
                continue
            content = str(item.get("content") or "").strip()
            if len(content) > max_chars:
                content = content[:max_chars] + "...[truncated]"
            preview.append(
                {
                    "index": idx,
                    "role": str(item.get("role") or "unknown"),
                    "content_preview": content,
                }
            )
        return preview

    def _log_history_context(
        self,
        *,
        session_id: Optional[str],
        conversation_history: Optional[List[Dict[str, str]]],
        phase: str,
    ) -> None:
        logger.debug(
            "query pipeline history context",
            phase=phase,
            session_id=session_id or "default",
            history_count=len(list(conversation_history or [])),
            history_preview=self._history_preview(conversation_history),
        )

    @staticmethod
    def _count_unique_sources(result: Dict[str, Any]) -> int:
        seen = set()
        for ref in result.get("references", []) or []:
            key = str(ref.get("file_path") or ref.get("reference_id") or "")
            if key:
                seen.add(key)
        return len(seen)

    def _log_rewrite_decision(
        self,
        *,
        question: str,
        rewrite: QueryRewriteResult,
        session_id: Optional[str],
    ) -> None:
        logger.info(
            "query rewrite decision",
            session_id=session_id or "default",
            query_type=rewrite.query_type,
            understand_confidence=round(rewrite.confidence, 3),
            rewrite_confidence=round(rewrite.rewrite_confidence, 3),
            retrieval_query_count=len(rewrite.retrieval_queries),
            sub_query_count=len(rewrite.sub_queries),
            rewritten=bool(rewrite.canonical_query and rewrite.canonical_query != question),
            language_hint=rewrite.language_hint,
            preserved_intent=rewrite.preserved_intent,
        )

    def _log_retrieval_hit(
        self,
        *,
        session_id: Optional[str],
        query: str,
        result: Dict[str, Any],
        path: str,
        query_type: str,
    ) -> None:
        refs = result.get("references", []) or []
        logger.info(
            "query retrieval result",
            session_id=session_id or "default",
            path=path,
            query_type=query_type,
            query_preview=query[:120],
            response_chars=len(str(result.get("response", "") or "")),
            reference_count=len(refs),
            source_count=self._count_unique_sources(result),
        )

    def _log_mode_retrieval_hit(
        self,
        *,
        session_id: Optional[str],
        query: str,
        mode_results: Dict[str, Dict[str, Any]],
        primary_mode: str,
    ) -> None:
        mode_stats = {}
        for mode, result in mode_results.items():
            refs = result.get("references", []) or []
            mode_stats[mode] = {
                "response_chars": len(str(result.get("response", "") or "")),
                "reference_count": len(refs),
                "source_count": self._count_unique_sources(result),
            }
        logger.info(
            "query multi-mode retrieval result",
            session_id=session_id or "default",
            query_preview=query[:120],
            primary_mode=primary_mode,
            mode_count=len(mode_results),
            mode_stats=mode_stats,
        )

    @staticmethod
    def _format_multi_intent_section(sub_query: str, response_text: str) -> str:
        return f"Sub-query: {sub_query}\n{response_text.strip()}"

    @staticmethod
    def _format_multi_intent_answer(sections: List[str]) -> str:
        if not sections:
            return ""
        if len(sections) == 1:
            return sections[0]
        return "\n\n---\n\n".join(sections).strip()
