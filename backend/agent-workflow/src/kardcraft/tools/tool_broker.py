"""Unified tool broker for evidence access.

This module centralizes:
- History file listing (file-storage)
- Ragix retrieval/search
- On-demand file excerpt fetching
- Lazy indexing to Ragix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional, Callable

from kardcraft.utils.file_storage_client import (
    FileMetadata,
    download_conversation_file,
    get_conversation_files,
)
from kardcraft.utils.logger import logger

_ALLOWED_QUERY_MODES = {"mix", "naive", "local", "global", "hybrid", "bypass"}


def _normalize_query_mode(mode: str) -> str:
    normalized = str(mode or "mix").strip().lower()
    if normalized not in _ALLOWED_QUERY_MODES:
        raise ValueError(
            "Unsupported Ragix query mode: "
            f"{mode!r}. Allowed modes: {sorted(_ALLOWED_QUERY_MODES)}"
        )
    return normalized


def _safe_decode_bytes(content: bytes) -> str:
    if not content:
        return ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except Exception:
            continue
    return ""


def _build_excerpt_from_text(
    content: str,
    *,
    query: Optional[str],
    locator: Optional[str],
    max_chars: int,
) -> str:
    if not content:
        return ""
    max_chars = max(200, min(max_chars, 20000))
    text = content.strip()
    if not text:
        return ""

    needle = (query or locator or "").strip()
    if not needle:
        return text[:max_chars]

    idx = text.lower().find(needle.lower())
    if idx < 0:
        return text[:max_chars]

    radius = (max_chars - len(needle)) // 2
    radius = max(0, radius)
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "... " + excerpt
    if end < len(text):
        excerpt = excerpt + " ..."
    return excerpt


def _normalize_refs(raw_refs: Any) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    if not isinstance(raw_refs, list):
        return refs
    for idx, item in enumerate(raw_refs):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("file_id") or item.get("doc_id") or "").strip()
        snippet = str(item.get("snippet") or item.get("content") or "").strip()
        refs.append(
            {
                "ref_id": str(item.get("ref_id") or source or f"ref_{idx+1}"),
                "source_type": str(item.get("source_type") or "ragix"),
                "source_id": source,
                "title": str(item.get("title") or item.get("filename") or source),
                "snippet": snippet[:800],
                "score": item.get("score"),
                "metadata": item,
            }
        )
    return refs

def _parse_rate_limit_env() -> int:
    raw = os.getenv("TOOL_BROKER_RATE_LIMIT_PER_MIN", "120")
    try:
        return int(raw)
    except ValueError:
        return 120

@dataclass
class ToolBroker:
    ragix_factory: Optional[Callable[[], Any]] = None
    default_rate_limit: int = field(default_factory=_parse_rate_limit_env)

    _ragix_client: Optional[Any] = None
    _call_counters: Dict[str, int] | None = None
    _counter_window: str = ""

    async def _get_ragix(self) -> Any:
        if self._ragix_client is not None:
            return self._ragix_client
        factory = self.ragix_factory
        if factory is None:
            from kardcraft.ragix import RagixClient

            factory = RagixClient
        client = factory()
        if hasattr(client, "initialize"):
            await client.initialize()
        self._ragix_client = client
        return client

    def _key(self, tool_name: str, session_id: Optional[str], user_id: Optional[str]) -> str:
        sid = (session_id or "none").strip() or "none"
        uid = (user_id or "none").strip() or "none"
        return f"{tool_name}:{sid}:{uid}"

    def _apply_rate_limit(
        self,
        *,
        tool_name: str,
        session_id: Optional[str],
        user_id: Optional[str],
        limit: Optional[int] = None,
    ) -> None:
        now_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        if self._counter_window != now_bucket or self._call_counters is None:
            self._counter_window = now_bucket
            self._call_counters = {}
        limit = max(1, int(limit or self.default_rate_limit))
        key = self._key(tool_name, session_id, user_id)
        count = int(self._call_counters.get(key, 0)) + 1
        self._call_counters[key] = count
        if count > limit:
            raise RuntimeError(
                f"tool broker rate limit exceeded: tool={tool_name} session={session_id} "
                f"user={user_id} count={count} limit={limit}"
            )

    def _audit(
        self,
        *,
        tool_name: str,
        session_id: Optional[str],
        user_id: Optional[str],
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "tool_name": tool_name,
            "session_id": session_id,
            "user_id": user_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }
        logger.info("tool_broker_audit", **payload)

    def _require_identity(
        self,
        *,
        tool_name: str,
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        if not str(session_id or "").strip():
            raise ValueError(f"{tool_name} requires non-empty session_id")
        if not str(user_id or "").strip():
            raise ValueError(f"{tool_name} requires non-empty user_id")

    async def list_history_files(self, *, session_id: str, user_id: str) -> Dict[str, Any]:
        self._require_identity(tool_name="list_history_files", session_id=session_id, user_id=user_id)
        self._apply_rate_limit(tool_name="list_history_files", session_id=session_id, user_id=user_id)
        files = await get_conversation_files(user_id=user_id, session_id=session_id)
        items: List[Dict[str, Any]] = []
        for item in files:
            items.append(
                {
                    "file_id": item.file_id,
                    "filename": item.filename,
                    "mime_type": item.content_type,
                    "size": item.file_size,
                    "uploaded_at": item.uploaded_at.isoformat() if item.uploaded_at else "",
                    "status": "active",
                    "pinned": False,
                    "index_state": "unknown",
                    "workspace_presence": "unknown",
                }
            )
        result = {
            "session_id": session_id,
            "user_id": user_id,
            "files": items,
            "count": len(items),
        }
        self._audit(
            tool_name="list_history_files",
            session_id=session_id,
            user_id=user_id,
            status="ok",
            details={"count": len(items)},
        )
        return result

    async def index_file_to_ragix(
        self,
        *,
        session_id: Optional[str],
        file_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        self._require_identity(tool_name="index_file_to_ragix", session_id=session_id, user_id=user_id)
        self._apply_rate_limit(tool_name="index_file_to_ragix", session_id=session_id, user_id=user_id)
        ragix = await self._get_ragix()
        track_id = await ragix.add_document(file_id=file_id, user_id=user_id, session_id=session_id)
        logger.info(
            "tool_broker index_file_to_ragix",
            session_id=session_id,
            file_id=file_id,
            user_id=user_id,
            track_id=track_id,
        )
        result = {
            "session_id": session_id,
            "file_id": file_id,
            "track_id": str(track_id or ""),
            "status": "indexed" if track_id else "submitted",
        }
        self._audit(
            tool_name="index_file_to_ragix",
            session_id=session_id,
            user_id=user_id,
            status="ok",
            details={"file_id": file_id, "track_id": str(track_id or "")},
        )
        return result

    async def search_ragix(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        top_k: int = 10,
        mode: str = "mix",
    ) -> Dict[str, Any]:
        normalized_mode = _normalize_query_mode(mode)
        self._apply_rate_limit(tool_name="search_ragix", session_id=session_id, user_id=user_id)
        ragix = await self._get_ragix()
        result = await ragix.query(
            question=query,
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

        refs = [ref.dict() for ref in result_refs] if result_refs else []
        normalized_refs = _normalize_refs(refs)
        zero_references = bool(file_ids) and len(normalized_refs) == 0
        payload = {
            "content": result_text or "",
            "refs": normalized_refs,
            "hit_count": len(normalized_refs),
            "query": query,
            "mode": normalized_mode,
            "session_id": session_id,
            "file_ids": file_ids or [],
            "diagnostics": {
                "zero_references": zero_references,
                "response_chars": len(result_text or ""),
            },
        }
        if zero_references:
            logger.warning(
                "ragix_query_zero_references",
                session_id=session_id,
                user_id=user_id,
                mode=normalized_mode,
                top_k=top_k,
                file_count=len(file_ids or []),
                response_chars=len(result_text or ""),
                query_preview=(query or "")[:160],
            )
        self._audit(
            tool_name="search_ragix",
            session_id=session_id,
            user_id=user_id,
            status="degraded_zero_references" if zero_references else "ok",
            details={
                "query_len": len(query or ""),
                "mode": normalized_mode,
                "top_k": top_k,
                "hit_count": len(normalized_refs),
                "file_count": len(file_ids or []),
                "response_chars": len(result_text or ""),
            },
        )
        return payload

    async def fetch_file_excerpt(
        self,
        *,
        file_id: str,
        user_id: str,
        query: Optional[str] = None,
        locator: Optional[str] = None,
        max_chars: int = 2000,
    ) -> Dict[str, Any]:
        self._require_identity(tool_name="fetch_file_excerpt", session_id="n/a", user_id=user_id)
        self._apply_rate_limit(tool_name="fetch_file_excerpt", session_id="n/a", user_id=user_id)
        content_bytes, metadata = await download_conversation_file(user_id=user_id, file_id=file_id)
        filename = file_id
        if isinstance(metadata, FileMetadata):
            custom_meta = getattr(metadata, "custom_meta", None) or {}
            filename = custom_meta.get("original_filename") or file_id
        content_text = _safe_decode_bytes(content_bytes)
        excerpt = _build_excerpt_from_text(
            content_text,
            query=query,
            locator=locator,
            max_chars=max_chars,
        )

        logger.info(
            "tool_broker fetch_file_excerpt",
            file_id=file_id,
            user_id=user_id,
            max_chars=max_chars,
            excerpt_len=len(excerpt),
        )
        result = {
            "file_id": file_id,
            "filename": filename,
            "excerpt": excerpt,
            "query": query or "",
            "locator": locator or "",
            "max_chars": max_chars,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "refs": [
                {
                    "ref_id": f"file_excerpt:{file_id}",
                    "source_type": "file_excerpt",
                    "source_id": file_id,
                    "title": filename,
                    "snippet": excerpt[:800],
                    "score": None,
                    "metadata": {"query": query or "", "locator": locator or ""},
                }
            ],
        }
        self._audit(
            tool_name="fetch_file_excerpt",
            session_id=None,
            user_id=user_id,
            status="ok",
            details={
                "file_id": file_id,
                "query": query or "",
                "locator": locator or "",
                "excerpt_len": len(excerpt),
            },
        )
        return result


_tool_broker: Optional[ToolBroker] = None


def get_tool_broker() -> ToolBroker:
    global _tool_broker
    if _tool_broker is None:
        _tool_broker = ToolBroker()
    return _tool_broker
