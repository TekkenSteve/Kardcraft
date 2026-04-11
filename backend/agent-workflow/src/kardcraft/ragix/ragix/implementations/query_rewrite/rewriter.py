from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from kardcraft.llm.client import chat_complete
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger

_ALLOWED_QUERY_TYPES = {
    "context_dependent",
    "comparative",
    "vague_reference",
    "multi_intent",
    "rhetorical",
    "plain",
}

_UNDERSTAND_SYSTEM_PROMPT = (
    "You are QueryUnderstander for a multilingual enterprise RAG system. "
    "Classify query semantics into one label from: "
    "context_dependent, comparative, vague_reference, multi_intent, rhetorical, plain. "
    "Use semantic understanding and conversation context. "
    "Return strict JSON only."
)

_REWRITE_SYSTEM_PROMPT = (
    "You are QueryRewriter for a multilingual enterprise RAG system. "
    "Rewrite query semantically for retrieval while preserving user intent exactly. "
    "Never invent facts or constraints. "
    "For knowledge retrieval tasks, produce substantive content-seeking queries (concepts, facts, definitions, steps), "
    "not meta-queries about identifying/clarifying file titles or context labels. "
    "Do not rewrite into queries like 'clarify context of <title>' unless the user explicitly asked for metadata clarification. "
    "If hints.uploaded_file_titles is provided and the user refers to a document/file without a specific title, "
    "you may resolve the reference using one title from that list. "
    "When using a title from hints, copy it verbatim exactly as provided, do not translate, normalize, or paraphrase it. "
    "If intent is multi_intent, split into up to 3 sub-queries. "
    "Return strict JSON only."
)


@dataclass
class QueryRewriteConfig:
    enabled: bool = True
    understand_max_tokens: int = 220
    rewrite_max_tokens: int = 420
    min_confidence: float = 0.6
    max_history_turns: int = 8


@dataclass
class QueryRewriteResult:
    query_type: str
    confidence: float
    rewrite_confidence: float
    canonical_query: str
    retrieval_queries: List[str]
    sub_queries: List[str]
    preserved_intent: str
    language_hint: str


class QueryRewriter:
    def __init__(self, config: QueryRewriteConfig):
        self.config = config

    async def rewrite(
        self,
        query: str,
        *,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> QueryRewriteResult:
        if not self.config.enabled:
            return self._fallback(query)

        history = self._truncate_history(conversation_history or [])
        hints = hints or {}

        try:
            understanding = await self._understand(query=query, history=history, hints=hints)
        except Exception as exc:
            logger.warning("Query understanding failed, fallback to original query", error=str(exc))
            return self._fallback(query)

        try:
            rewritten = await self._rewrite(query=query, understanding=understanding, history=history, hints=hints)
        except Exception as exc:
            logger.warning("Query rewrite failed, fallback to original query", error=str(exc))
            return self._fallback(query, query_type=understanding.get("query_type", "plain"))

        result = self._normalize_rewrite_result(query=query, understanding=understanding, rewritten=rewritten)
        if result.rewrite_confidence < self.config.min_confidence:
            # Keep original query as high-priority fallback retrieval query.
            result.retrieval_queries = self._dedupe_queries([query, *result.retrieval_queries])
        return result

    async def _understand(
        self,
        *,
        query: str,
        history: List[Dict[str, str]],
        hints: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "query": query,
            "conversation_history": history,
            "hints": hints,
            "required_output": {
                "query_type": "context_dependent|comparative|vague_reference|multi_intent|rhetorical|plain",
                "confidence": "0~1",
                "requires_history": "bool",
                "preserved_intent": "string",
                "language_hint": "string",
                "reasoning_brief": "one sentence",
            },
        }
        resp = await chat_complete(
            intent="query_understand",
            temperature=0.0,
            messages=[
                {"role": "system", "content": _UNDERSTAND_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=self.config.understand_max_tokens,
        )
        content = self._extract_response_text(resp)
        parsed = safe_parse_llm_json(content, default={})
        return parsed if isinstance(parsed, dict) else {}

    async def _rewrite(
        self,
        *,
        query: str,
        understanding: Dict[str, Any],
        history: List[Dict[str, str]],
        hints: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "query": query,
            "understanding": understanding,
            "conversation_history": history,
            "hints": hints,
            "required_output": {
                "canonical_query": "string",
                "retrieval_queries": ["string"],
                "sub_queries": ["string"],
                "rewrite_confidence": "0~1",
                "rewrite_notes": {
                    "history_used": "bool",
                    "entity_resolution_applied": "bool",
                    "decomposition_applied": "bool",
                },
            },
        }
        resp = await chat_complete(
            intent="query_rewrite",
            temperature=0.0,
            messages=[
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=self.config.rewrite_max_tokens,
        )
        content = self._extract_response_text(resp)
        parsed = safe_parse_llm_json(content, default={})
        return parsed if isinstance(parsed, dict) else {}

    def _normalize_rewrite_result(
        self,
        *,
        query: str,
        understanding: Dict[str, Any],
        rewritten: Dict[str, Any],
    ) -> QueryRewriteResult:
        raw_type = str(understanding.get("query_type") or "plain").strip()
        query_type = raw_type if raw_type in _ALLOWED_QUERY_TYPES else "plain"
        confidence = self._coerce_confidence(understanding.get("confidence"), default=0.0)
        rewrite_confidence = self._coerce_confidence(rewritten.get("rewrite_confidence"), default=confidence)

        canonical = str(rewritten.get("canonical_query") or "").strip() or query
        retrieval_queries = self._dedupe_queries(
            [canonical, *(rewritten.get("retrieval_queries") or [])]
        )
        if not retrieval_queries:
            retrieval_queries = [query]

        raw_sub_queries = rewritten.get("sub_queries") or []
        sub_queries = self._dedupe_queries(raw_sub_queries, limit=3)
        if query_type != "multi_intent":
            sub_queries = []

        preserved_intent = str(understanding.get("preserved_intent") or "query").strip() or "query"
        language_hint = str(understanding.get("language_hint") or "unknown").strip() or "unknown"

        return QueryRewriteResult(
            query_type=query_type,
            confidence=confidence,
            rewrite_confidence=rewrite_confidence,
            canonical_query=canonical,
            retrieval_queries=retrieval_queries,
            sub_queries=sub_queries,
            preserved_intent=preserved_intent,
            language_hint=language_hint,
        )

    def _fallback(self, query: str, query_type: str = "plain") -> QueryRewriteResult:
        return QueryRewriteResult(
            query_type=query_type if query_type in _ALLOWED_QUERY_TYPES else "plain",
            confidence=0.0,
            rewrite_confidence=0.0,
            canonical_query=query,
            retrieval_queries=[query],
            sub_queries=[],
            preserved_intent="query",
            language_hint="unknown",
        )

    @staticmethod
    def _extract_response_text(resp: Any) -> str:
        try:
            if resp and getattr(resp, "choices", None):
                message = resp.choices[0].message
                return str(getattr(message, "content", "") or "")
        except Exception:
            return ""
        return ""

    def _truncate_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not history:
            return []
        trimmed = history[-self.config.max_history_turns :]
        out: List[Dict[str, str]] = []
        for turn in trimmed:
            role = str(turn.get("role") or "user").strip() or "user"
            content = str(turn.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": role, "content": content})
        return out

    @staticmethod
    def _coerce_confidence(value: Any, default: float) -> float:
        try:
            number = float(value)
            if number < 0:
                return 0.0
            if number > 1:
                return 1.0
            return number
        except Exception:
            return default

    @staticmethod
    def _dedupe_queries(values: List[Any], limit: int = 4) -> List[str]:
        out: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= limit:
                break
        return out
