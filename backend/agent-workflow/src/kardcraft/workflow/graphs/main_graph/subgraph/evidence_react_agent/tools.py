"""Tools for evidence ReAct agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.logger import logger
from kardcraft.utils.main_graph_helpers import information_gain, query_token_set
from kardcraft.workflow.graphs.main_graph.prompt import build_node_query


def normalize_query_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _ref_source_key(ref: Dict[str, Any]) -> str:
    if not isinstance(ref, dict):
        return ""
    return str(
        ref.get("source_id")
        or ref.get("file_id")
        or ref.get("doc_id")
        or ref.get("ref_id")
        or ""
    ).strip()


def _count_unique_ref_sources(refs: List[Dict[str, Any]]) -> int:
    seen: set[str] = set()
    for ref in refs:
        key = _ref_source_key(ref)
        if key:
            seen.add(key)
    return len(seen)


def _node_semantic_tokens(node: Dict[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(node.get("title") or ""),
            str(node.get("summary") or ""),
            str(node.get("doc_title") or node.get("doc_name") or ""),
        ]
    )
    return query_token_set(text)


def _evaluate_grounded_hit(
    *,
    node: Dict[str, Any],
    content: str,
    refs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    source_count = _count_unique_ref_sources(refs)
    if not content:
        return {"hit": False, "reason_code": "miss", "source_count": source_count, "content_tokens": 0, "node_overlap": 0}
    if source_count <= 0:
        return {"hit": False, "reason_code": "ungrounded", "source_count": source_count, "content_tokens": 0, "node_overlap": 0}

    content_tokens = query_token_set(content)
    token_count = len(content_tokens)
    node_tokens = _node_semantic_tokens(node)
    overlap = len(content_tokens & node_tokens)
    overlap_ratio = (overlap / max(1, len(node_tokens))) if node_tokens else 0.0

    # Require minimum semantic density and node relevance to avoid placeholder responses
    # being treated as valid evidence.
    if token_count < 6:
        return {
            "hit": False,
            "reason_code": "low_quality",
            "source_count": source_count,
            "content_tokens": token_count,
            "node_overlap": overlap,
            "overlap_ratio": round(overlap_ratio, 4),
        }
    if node_tokens and overlap == 0 and overlap_ratio < 0.08:
        return {
            "hit": False,
            "reason_code": "low_quality",
            "source_count": source_count,
            "content_tokens": token_count,
            "node_overlap": overlap,
            "overlap_ratio": round(overlap_ratio, 4),
        }
    return {
        "hit": True,
        "reason_code": "hit",
        "source_count": source_count,
        "content_tokens": token_count,
        "node_overlap": overlap,
        "overlap_ratio": round(overlap_ratio, 4),
    }


@dataclass(slots=True)
class EvidenceReactToolContext:
    candidates: List[Dict[str, Any]]
    node_map: Dict[str, Dict[str, Any]]
    user_input: str
    query_scope: str
    max_nodes_per_round: int
    max_rag_calls: int
    min_gain: float
    low_gain_limit: int
    top_k: int
    session_id: Optional[str]
    user_id: Optional[str]
    file_ids: List[str]

    cursor: int = 0
    rag_calls: int = 0
    low_gain_rounds: int = 0
    selected_nodes: List[Dict[str, Any]] = field(default_factory=list)
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    gains: List[float] = field(default_factory=list)
    aggregated_knowledge: str = ""
    duplicate_queries: int = 0
    hit_count: int = 0
    miss_count: int = 0
    ungrounded_count: int = 0
    degraded_zero_ref_count: int = 0
    low_quality_count: int = 0
    retrieval_events: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "budget_exhausted"
    queried_ids: set[str] = field(default_factory=set)

    def min_rag_calls_before_low_gain_stop(self) -> int:
        if self.query_scope == "title_only":
            return 1
        return min(self.max_rag_calls, max(self.low_gain_limit + 1, 4))

    def next_nodes(self, batch_size: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        wanted = max(1, min(batch_size, self.max_nodes_per_round))
        while self.cursor < len(self.candidates) and len(out) < wanted:
            node = self.candidates[self.cursor]
            self.cursor += 1
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "").strip()
            if not node_id or node_id in self.queried_ids:
                continue
            out.append(node)
        return out

    async def query_node_evidence(self, node_id: str) -> Dict[str, Any]:
        nid = str(node_id or "").strip()
        if not nid:
            return {"ok": False, "reason": "empty_node_id"}
        if self.rag_calls >= self.max_rag_calls:
            self.stop_reason = "max_rag_calls_reached"
            return {"ok": False, "reason": "max_rag_calls_reached"}

        node = self.node_map.get(nid)
        if not node:
            return {"ok": False, "reason": "unknown_node_id", "node_id": nid}
        if nid in self.queried_ids:
            self.duplicate_queries += 1
            self.retrieval_events.append({"query": nid, "reason_code": "duplicate"})
            return {"ok": False, "reason": "duplicate_node", "node_id": nid}

        self.queried_ids.add(nid)
        query = build_node_query(self.user_input, node, include_user_input=True)
        self.rag_calls += 1
        result = await query_knowledge.ainvoke(
            {
                "query": query,
                "mode": "mix",
                "top_k": self.top_k,
                "session_id": self.session_id,
                "file_ids": self.file_ids,
                "user_id": self.user_id,
            }
        )
        content = str(result.get("content") or "").strip()
        raw_refs = result.get("refs") or []
        refs = [item for item in raw_refs if isinstance(item, dict)]
        diagnostics = result.get("diagnostics") if isinstance(result, dict) else {}
        zero_ref_degraded = bool(isinstance(diagnostics, dict) and diagnostics.get("zero_references"))
        hit_eval = _evaluate_grounded_hit(node=node, content=content, refs=refs)
        source_count = int(hit_eval.get("source_count") or 0)
        grounded = bool(hit_eval.get("hit"))
        reason_code = str(hit_eval.get("reason_code") or "miss")
        if reason_code == "ungrounded" and zero_ref_degraded:
            reason_code = "backend_degraded"
        gain = information_gain(content, self.aggregated_knowledge) if grounded else 0.0
        self.gains.append(round(gain, 4))

        if grounded:
            self.hit_count += 1
            self.retrieval_events.append({"query": query, "reason_code": "hit"})
            self.selected_nodes.append(node)
            self.evidence_items.append(
                {
                    "query": query,
                    "content": content[:2000],
                    "refs": refs,
                    "node": node,
                    "information_gain": gain,
                    "reason_codes": ["hit"],
                }
            )
            self.aggregated_knowledge = f"{self.aggregated_knowledge}\n\n{content[:2000]}".strip()
        else:
            self.miss_count += 1
            if reason_code == "ungrounded":
                self.ungrounded_count += 1
            elif reason_code == "backend_degraded":
                self.degraded_zero_ref_count += 1
            elif reason_code == "low_quality":
                self.low_quality_count += 1
            self.retrieval_events.append({"query": query, "reason_code": reason_code})

        logger.debug(
            "evidence retrieval judged",
            node_id=nid,
            reason_code=reason_code,
            source_count=source_count,
            content_chars=len(content),
            content_tokens=int(hit_eval.get("content_tokens") or 0),
            node_overlap=int(hit_eval.get("node_overlap") or 0),
            information_gain=round(gain, 4),
            rag_calls=self.rag_calls,
            stop_reason=self.stop_reason,
        )

        if gain < self.min_gain:
            self.low_gain_rounds += 1
        else:
            self.low_gain_rounds = 0

        if self.query_scope == "title_only" and self.evidence_items:
            self.stop_reason = "title_only_sufficient"
        elif (
            self.low_gain_rounds >= self.low_gain_limit
            and self.rag_calls >= self.min_rag_calls_before_low_gain_stop()
        ):
            self.stop_reason = "low_information_gain"
        elif self.rag_calls >= self.max_rag_calls:
            self.stop_reason = "max_rag_calls_reached"

        return {
            "ok": True,
            "node_id": nid,
            "hit": grounded,
            "reference_count": len(refs),
            "source_count": source_count,
            "reason_code": reason_code,
            "information_gain": round(gain, 4),
            "rag_calls": self.rag_calls,
            "stop_reason": self.stop_reason,
            "content_preview": content[:240],
            "node_overlap": int(hit_eval.get("node_overlap") or 0),
            "content_token_count": int(hit_eval.get("content_tokens") or 0),
        }

    def current_progress(self) -> Dict[str, Any]:
        return {
            "candidate_nodes": len(self.candidates),
            "queried_nodes": len(self.queried_ids),
            "selected_nodes": len(self.selected_nodes),
            "rag_calls": self.rag_calls,
            "max_rag_calls": self.max_rag_calls,
            "low_gain_rounds": self.low_gain_rounds,
            "low_gain_limit": self.low_gain_limit,
            "min_rag_calls_before_low_gain_stop": self.min_rag_calls_before_low_gain_stop(),
            "stop_reason": self.stop_reason,
        }


def build_evidence_react_tools(ctx: EvidenceReactToolContext) -> list:
    @tool
    def get_next_nodes(batch_size: int = 1) -> Dict[str, Any]:
        """Get next candidate outline nodes for retrieval."""
        nodes = ctx.next_nodes(batch_size)
        return {
            "nodes": [
                {
                    "node_id": str(node.get("node_id") or ""),
                    "title": str(node.get("title") or ""),
                    "summary": str(node.get("summary") or ""),
                    "doc_title": str(node.get("doc_title") or node.get("doc_name") or ""),
                    "depth": int(node.get("depth") or 0),
                    "priority": float(node.get("priority") or 0.0),
                }
                for node in nodes
            ],
            "remaining_candidates": max(0, len(ctx.candidates) - ctx.cursor),
            "rag_calls": ctx.rag_calls,
            "max_rag_calls": ctx.max_rag_calls,
        }

    @tool
    async def query_node_evidence(node_id: str) -> Dict[str, Any]:
        """Query evidence for a candidate node id."""
        return await ctx.query_node_evidence(node_id)

    @tool
    def current_progress() -> Dict[str, Any]:
        """Inspect current retrieval progress and stop signals."""
        return ctx.current_progress()

    return [get_next_nodes, query_node_evidence, current_progress]
