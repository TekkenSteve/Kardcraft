"""Knowledge Tools - Stateless RAGix Query Tools.

These are pure function capabilities extracted from syllabus_agent:
- query_knowledge: Query knowledge base via LightRAG
- progressive_query: Progressive disclosure via LightRAG modes
- enrich_with_context: Enrich content with additional context

All tools are stateless and can be called from any agent via main_graph routing.
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Literal

from langchain_core.tools import tool

from kardcraft.utils.logger import logger

_ragix_client: Optional[Any] = None
_ALLOWED_QUERY_MODES = {"mix", "naive", "local", "global", "hybrid", "bypass"}


def _normalize_query_mode(mode: str) -> str:
    normalized = str(mode or "mix").strip().lower()
    if normalized not in _ALLOWED_QUERY_MODES:
        raise ValueError(
            "Unsupported Ragix query mode: "
            f"{mode!r}. Allowed modes: {sorted(_ALLOWED_QUERY_MODES)}"
        )
    return normalized

async def _get_ragix_client() -> Optional[Any]:
    """Get or create RagixClient instance."""
    global _ragix_client
    if _ragix_client is not None:
        return _ragix_client

    try:
        from kardcraft.ragix import RagixClient

        client = RagixClient()
        await client.initialize()
        logger.info("Ragix client initialized for tools")
        _ragix_client = client
        return client

    except Exception as e:
        logger.warning(f"Ragix initialization failed: {e}")
        return None


@tool
async def query_knowledge(
    query: str,
    session_id: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    mode: Literal["mix", "naive", "local", "global", "hybrid", "bypass"] = "mix",
    top_k: int = 10,
) -> Dict[str, Any]:
    """Query the knowledge base using LightRAG.

    Args:
        query: The search query string
        session_id: Optional session ID for workspace isolation
        file_ids: Optional list of file IDs to restrict search
        user_id: Optional user ID for file retrieval
        mode: Query mode - "mix", "naive", "local", or "global"
        top_k: Number of results to return (default: 10)

    Returns:
        Dict with keys:
        - content: Retrieved text content
        - refs: List of reference dicts with source info
        - query: The query that was executed
        - mode: Query mode used
        - file_ids: File IDs searched
    """
    normalized_mode = _normalize_query_mode(mode)

    logger.info(
        "query_knowledge tool called",
        query=query[:100],
        session_id=bool(session_id),
        file_count=len(file_ids) if file_ids else 0,
        mode=normalized_mode,
    )

    try:
        ragix = await _get_ragix_client()

        if ragix is None:
            logger.warning("Ragix client unavailable")
            return {
                "content": "",
                "refs": [],
                "query": query,
                "mode": normalized_mode,
                "file_ids": file_ids or [],
                "error": "Ragix client unavailable",
            }

        result = await ragix.query(
            query,
            session_id=session_id,
            file_ids=file_ids,
            user_id=user_id,
            top_k=top_k,
            mode=normalized_mode,
        )

        result_text = getattr(result, "text", None)
        if result_text is None:
            result_text = getattr(result, "content", "")

        result_refs = getattr(result, "citations", None)
        if result_refs is None:
            result_refs = getattr(result, "refs", []) if result else []

        query_record = {
            "query": query,
            "mode": normalized_mode,
            "file_ids": file_ids or [],
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "result_length": len(result_text) if result_text else 0,
        }

        context_entry = {
            "content": result_text or "",
            "refs": [ref.dict() for ref in result_refs] if result_refs else [],
            "query": query,
            "mode": normalized_mode,
            "file_ids": file_ids or [],
        }

        logger.info(
            "query_knowledge complete",
            result_length=len(result_text) if result_text else 0,
        )

        return {
            "content": result_text or "",
            "refs": context_entry["refs"],
            "query": query,
            "mode": normalized_mode,
            "file_ids": file_ids or [],
            "query_record": query_record,
            "context_entry": context_entry,
        }

    except Exception as e:
        logger.error(f"query_knowledge failed: {e}")
        return {
            "content": "",
            "refs": [],
            "query": query,
            "mode": normalized_mode,
            "file_ids": file_ids or [],
            "error": str(e),
        }


@tool
async def progressive_query(
    focus_area: str,
    session_id: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    max_depth: int = 2,
    top_k: int = 5,
) -> Dict[str, Any]:
    """Progressive disclosure query using LightRAG modes.

    Executes queries at increasing depth levels (naive -> local -> global)
    to progressively gather more context.

    Args:
        focus_area: The topic/focus area to research
        session_id: Optional session ID for workspace isolation
        file_ids: Optional list of file IDs to restrict search
        user_id: Optional user ID for file retrieval
        max_depth: Maximum depth level (0-2, default: 2)
        top_k: Number of results per level (default: 5)

    Returns:
        Dict with keys:
        - results: List of results per depth level
        - focus_area: The focus area queried
        - max_depth: Maximum depth used
        - content: Combined content from all levels
    """
    logger.info(
        "progressive_query tool called",
        focus=focus_area[:100],
        max_depth=max_depth,
    )

    try:
        ragix = await _get_ragix_client()

        if ragix is None:
            logger.warning("Ragix client unavailable for progressive query")
            return {
                "results": [],
                "focus_area": focus_area,
                "max_depth": max_depth,
                "content": "",
                "error": "Ragix client unavailable",
            }

        results = []

        for depth in range(max_depth + 1):
            mode = ["naive", "local", "global"][min(depth, 2)]

            answer = await ragix.query(
                focus_area,
                session_id=session_id,
                file_ids=file_ids,
                user_id=user_id,
                top_k=top_k,
                mode=mode,
            )

            answer_text = getattr(answer, "text", None)
            if answer_text is None:
                answer_text = getattr(answer, "content", "")

            answer_refs = getattr(answer, "citations", None)
            if answer_refs is None:
                answer_refs = getattr(answer, "refs", []) if answer else []

            results.append(
                {
                    "depth": depth,
                    "mode": mode,
                    "content": answer_text or "",
                    "refs": [ref.dict() for ref in answer_refs] if answer_refs else [],
                }
            )

            if answer_text and len(answer_text) > 2000:
                logger.info(f"Progressive query: depth {depth} reached threshold")
                break

        query_record = {
            "query": focus_area,
            "mode": "progressive",
            "max_depth": max_depth,
            "results": results,
            "timestamp": datetime.now().isoformat(),
        }

        context_entry = {
            "content": "\n\n".join([r["content"] for r in results]),
            "focus_area": focus_area,
            "progressive_results": results,
        }

        return {
            "results": results,
            "focus_area": focus_area,
            "max_depth": max_depth,
            "content": context_entry["content"],
            "query_record": query_record,
            "context_entry": context_entry,
        }

    except Exception as e:
        logger.error(f"progressive_query failed: {e}")
        return {
            "results": [],
            "focus_area": focus_area,
            "max_depth": max_depth,
            "content": "",
            "error": str(e),
        }


@tool
async def enrich_with_context(
    content: str,
    focus_areas: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    mode: str = "local",
    top_k: int = 5,
) -> Dict[str, Any]:
    """Enrich content with additional context from knowledge base.

    Args:
        content: The content to enrich
        focus_areas: Optional list of focus areas to query
        session_id: Optional session ID for workspace isolation
        file_ids: Optional list of file IDs to restrict search
        user_id: Optional user ID for file retrieval
        mode: Query mode - "mix", "naive", "local", or "global" (default: "local")
        top_k: Number of results to return (default: 5)

    Returns:
        Dict with keys:
        - original_content: The original content passed in
        - enriched_content: The original + retrieved context
        - retrieved_content: The retrieved context
        - refs: List of reference dicts
        - focus_areas: Focus areas queried
    """
    logger.info(
        "enrich_with_context tool called",
        content_length=len(content),
        focus_count=len(focus_areas) if focus_areas else 0,
        mode=mode,
    )

    if not focus_areas:
        focus_areas = []

    try:
        ragix = await _get_ragix_client()

        if ragix is None:
            logger.warning("Ragix client unavailable for enrichment")
            return {
                "original_content": content,
                "enriched_content": content,
                "retrieved_content": "",
                "refs": [],
                "focus_areas": focus_areas,
                "error": "Ragix client unavailable",
            }

        # Build query from focus areas
        query = " ".join(focus_areas) if focus_areas else content[:500]

        result = await ragix.query(
            query,
            session_id=session_id,
            file_ids=file_ids,
            user_id=user_id,
            top_k=top_k,
            mode=mode,
        )

        retrieved_content = result.content if result else ""
        refs = [ref.dict() for ref in result.refs] if result and result.refs else []

        # Combine original with retrieved
        enriched_content = (
            f"{content}\n\n--- Additional Context ---\n{retrieved_content}"
        )

        logger.info(
            "enrich_with_context complete",
            retrieved_length=len(retrieved_content),
        )

        return {
            "original_content": content,
            "enriched_content": enriched_content,
            "retrieved_content": retrieved_content,
            "refs": refs,
            "focus_areas": focus_areas,
        }

    except Exception as e:
        logger.error(f"enrich_with_context failed: {e}")
        return {
            "original_content": content,
            "enriched_content": content,
            "retrieved_content": "",
            "refs": [],
            "focus_areas": focus_areas,
            "error": str(e),
        }


# Export list for easy importing
knowledge_tools = [query_knowledge, progressive_query, enrich_with_context]
