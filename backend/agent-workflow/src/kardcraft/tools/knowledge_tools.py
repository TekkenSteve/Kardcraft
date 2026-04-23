"""Knowledge Tools - Stateless RAGix Query Tools.

These are pure function capabilities extracted from syllabus_agent:
- query_knowledge: Query knowledge base via LightRAG
- progressive_query: Progressive disclosure via LightRAG modes
- enrich_with_context: Enrich content with additional context

All tools are stateless and can be called from any agent via main_graph routing.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional, Literal

from langchain_core.tools import tool

from kardcraft.tools.tool_broker import get_tool_broker
from kardcraft.utils.logger import logger

async def _search_via_broker(
    *,
    query: str,
    session_id: Optional[str],
    file_ids: Optional[List[str]],
    user_id: Optional[str],
    top_k: int,
    mode: str,
) -> Dict[str, Any]:
    """Delegate query execution/validation to the unified ToolBroker."""
    broker = get_tool_broker()
    return await broker.search_ragix(
        query=query,
        session_id=session_id,
        file_ids=file_ids,
        user_id=user_id,
        top_k=top_k,
        mode=mode,
    )

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
    logger.info(
        "query_knowledge tool called",
        query=query[:100],
        session_present=bool(session_id),
        session_id=(session_id or "default"),
        file_count=len(file_ids) if file_ids else 0,
        mode=mode,
    )

    try:
        result = await _search_via_broker(
            query=query,
            session_id=session_id,
            file_ids=file_ids,
            user_id=user_id,
            top_k=top_k,
            mode=mode,
        )
        normalized_mode = str(result.get("mode") or mode or "mix").strip().lower()
        result_text = str(result.get("content") or "")
        result_refs = result.get("refs") or []
        diagnostics = result.get("diagnostics") if isinstance(result, dict) else {}

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
            "refs": result_refs,
            "query": query,
            "mode": normalized_mode,
            "file_ids": file_ids or [],
            "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
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
            "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
            "query_record": query_record,
            "context_entry": context_entry,
        }

    except Exception as e:
        logger.error(f"query_knowledge failed: {e}")
        fallback_mode = str(mode or "mix").strip().lower()
        return {
            "content": "",
            "refs": [],
            "query": query,
            "mode": fallback_mode,
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
        results = []

        for depth in range(max_depth + 1):
            mode = ["naive", "local", "global"][min(depth, 2)]

            answer = await _search_via_broker(
                query=focus_area,
                session_id=session_id,
                file_ids=file_ids,
                user_id=user_id,
                top_k=top_k,
                mode=mode,
            )
            answer_text = str(answer.get("content") or "")
            answer_refs = answer.get("refs") or []

            results.append(
                {
                    "depth": depth,
                    "mode": mode,
                    "content": answer_text or "",
                    "refs": answer_refs,
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
        # Build query from focus areas
        query = " ".join(focus_areas) if focus_areas else content[:500]
        result = await _search_via_broker(
            query=query,
            session_id=session_id,
            file_ids=file_ids,
            user_id=user_id,
            top_k=top_k,
            mode=mode,
        )

        retrieved_content = str(result.get("content") or "")
        refs = result.get("refs") or []

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


@tool
async def list_history_files(
    session_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """List history files in current session via unified tool broker."""
    broker = get_tool_broker()
    return await broker.list_history_files(session_id=session_id, user_id=user_id)


@tool
async def index_file_to_ragix(
    file_id: str,
    user_id: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger lazy index of a file to Ragix via unified tool broker."""
    broker = get_tool_broker()
    return await broker.index_file_to_ragix(
        session_id=session_id,
        file_id=file_id,
        user_id=user_id,
    )


@tool
async def fetch_file_excerpt(
    file_id: str,
    user_id: str,
    query: Optional[str] = None,
    locator: Optional[str] = None,
    max_chars: int = 2000,
) -> Dict[str, Any]:
    """Fetch a targeted file excerpt via unified tool broker."""
    broker = get_tool_broker()
    return await broker.fetch_file_excerpt(
        file_id=file_id,
        user_id=user_id,
        query=query,
        locator=locator,
        max_chars=max_chars,
    )


# Export list for easy importing
knowledge_tools = [
    query_knowledge,
    progressive_query,
    enrich_with_context,
    list_history_files,
    index_file_to_ragix,
    fetch_file_excerpt,
]
