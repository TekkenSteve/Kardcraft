"""Incremental per-file document-tree registry for file-driven card generation."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pymupdf

from kardcraft.llm.client import chat_complete
from kardcraft.pageindex import (
    PageIndexBuildConfig,
    build_document_tree_async,
    flatten_nodes,
)
from kardcraft.ragix.ragix.utils.gotenberg_client import (
    GotenbergConversionError,
    GotenbergConverterClient,
)
from kardcraft.services.redis import get as redis_get
from kardcraft.services.redis import set as redis_set
from kardcraft.tools.knowledge_tools import query_knowledge
from kardcraft.utils.file_storage_client import download_conversation_file
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger

_REGISTRY_PREFIX = "kardcraft:doc_tree_registry:v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_key(session_id: str) -> str:
    return f"{_REGISTRY_PREFIX}:{session_id}"


def _dedupe_key(kind: str, content: str) -> str:
    digest = hashlib.sha1(f"{kind}:{content}".encode("utf-8")).hexdigest()
    return digest


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _guess_source_extension(metadata: Any) -> str:
    custom_meta = getattr(metadata, "custom_meta", {}) or {}
    filename = (
        _as_str(custom_meta.get("original_filename"))
        or _as_str(custom_meta.get("filename"))
        or _as_str(custom_meta.get("name"))
    )
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower().strip()
        if ext:
            return ext
    return ""


def _convert_to_pdf_bytes(file_bytes: bytes, metadata: Any) -> bytes:
    source_ext = _guess_source_extension(metadata)
    if source_ext == ".pdf":
        return bytes(file_bytes)

    suffix = source_ext if source_ext else ".bin"
    temp_in_path: str | None = None
    prepared = None
    converter = GotenbergConverterClient()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            tmp_in.write(file_bytes)
            temp_in_path = tmp_in.name
        prepared = converter.prepare_for_parse(temp_in_path, enabled=True)
        parse_path = _as_str(prepared.parse_path)
        if _as_str(prepared.parse_ext).lower() != ".pdf" or not parse_path or not os.path.exists(parse_path):
            raise ValueError("gotenberg_prepare_non_pdf")
        with open(parse_path, "rb") as fp:
            converted = fp.read()
        return converted
    except GotenbergConversionError as exc:
        raise ValueError(f"gotenberg_conversion_failed:{exc}") from exc
    finally:
        if prepared is not None:
            try:
                prepared.cleanup()
            except Exception:
                pass
        if temp_in_path and os.path.exists(temp_in_path):
            try:
                os.remove(temp_in_path)
            except Exception:
                pass


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return 0
    try:
        return int(doc.page_count or 0)
    finally:
        doc.close()


def _is_low_quality_tree(*, tree: Dict[str, Any], file_id: str, pdf_page_count: int) -> bool:
    placeholder_markers = (
        "[no-context]",
        "no context available",
        "not able to provide an answer",
        "unable to provide an answer",
    )

    def _contains_placeholder(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        text = " ".join(
            _as_str(node.get(key)).lower()
            for key in ("title", "summary", "doc_description")
        )
        if any(marker in text for marker in placeholder_markers):
            return True
        return any(_contains_placeholder(child) for child in (node.get("nodes") or []))

    if _contains_placeholder(tree):
        return True

    if pdf_page_count < 3:
        return False
    doc_name = _as_str(tree.get("doc_name")) or file_id
    doc_title = _as_str(tree.get("title")) or doc_name
    refs = flatten_nodes(
        file_id=file_id,
        doc_name=doc_name,
        doc_title=doc_title,
        nodes=tree.get("nodes") or [],
        include_root=False,
        root=tree,
    )
    if len(refs) < 4:
        return False
    covered_pages: set[int] = set()
    for ref in refs:
        start = int(ref.get("start_index") or 1)
        end = int(ref.get("end_index") or start)
        covered_pages.add(max(1, start))
        covered_pages.add(max(1, end))
    return len(covered_pages) <= 1


def _safe_json_loads(raw: str | None) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _empty_registry(session_id: str, user_id: str) -> Dict[str, Any]:
    return {
        "schema_version": "doc_tree_registry.v1",
        "session_id": session_id,
        "user_id": user_id,
        "files": {},
        "knowledge_history": [],
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }


def _normalize_history_entries(entries: Any) -> List[Dict[str, str]]:
    if not isinstance(entries, list):
        return []
    normalized: List[Dict[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        kind = _as_str(item.get("kind"))
        content = _as_str(item.get("content"))
        if not kind or not content:
            continue
        normalized.append(
            {
                "kind": kind,
                "content": content,
                "fingerprint": _as_str(item.get("fingerprint")) or _dedupe_key(kind, content),
                "added_at": _as_str(item.get("added_at")) or _utc_now(),
            }
        )
    return normalized


async def _load_registry(session_id: str, user_id: str) -> Dict[str, Any]:
    raw = await redis_get(_registry_key(session_id))
    parsed = _safe_json_loads(raw)
    if not parsed:
        return _empty_registry(session_id=session_id, user_id=user_id)
    parsed.setdefault("schema_version", "doc_tree_registry.v1")
    parsed.setdefault("session_id", session_id)
    parsed.setdefault("user_id", user_id)
    parsed.setdefault("files", {})
    parsed["knowledge_history"] = _normalize_history_entries(parsed.get("knowledge_history"))
    parsed.setdefault("created_at", _utc_now())
    parsed.setdefault("updated_at", _utc_now())
    return parsed


async def _save_registry(session_id: str, registry: Dict[str, Any]) -> None:
    registry["updated_at"] = _utc_now()
    await redis_set(_registry_key(session_id), json.dumps(registry, ensure_ascii=False), ex=7 * 24 * 3600)


def _extract_new_knowledge(
    *,
    user_input: str,
    message_knowledge: str,
    conversation_history: List[Dict[str, Any]] | None,
) -> List[Tuple[str, str]]:
    output: List[Tuple[str, str]] = []
    if _as_str(user_input):
        output.append(("user_input", _as_str(user_input)))
    if _as_str(message_knowledge):
        output.append(("message_knowledge", _as_str(message_knowledge)))
    history = conversation_history or []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        role = _as_str(item.get("role")).lower()
        content = _as_str(item.get("content"))
        if role == "user" and content:
            output.append(("conversation_user", content))
    return output


def _append_knowledge_history(
    registry: Dict[str, Any],
    items: List[Tuple[str, str]],
) -> None:
    history = _normalize_history_entries(registry.get("knowledge_history"))
    known = {entry.get("fingerprint") for entry in history}
    for kind, content in items:
        fingerprint = _dedupe_key(kind, content)
        if fingerprint in known:
            continue
        history.append(
            {
                "kind": kind,
                "content": content,
                "fingerprint": fingerprint,
                "added_at": _utc_now(),
            }
        )
        known.add(fingerprint)
    # Keep bounded history to avoid unbounded growth.
    registry["knowledge_history"] = history[-200:]


async def _build_one_document_tree(
    *,
    file_id: str,
    user_id: str,
    model: str | None,
) -> Dict[str, Any]:
    file_bytes, metadata = await download_conversation_file(user_id=user_id, file_id=file_id)
    filename = (
        (metadata.custom_meta or {}).get("original_filename")
        or (metadata.custom_meta or {}).get("filename")
        or file_id
    )
    pdf_bytes = await asyncio.to_thread(_convert_to_pdf_bytes, file_bytes, metadata)
    pdf_page_count = await asyncio.to_thread(_count_pdf_pages, pdf_bytes)
    stream = io.BytesIO(pdf_bytes)
    config = PageIndexBuildConfig(model=model)
    tree = await build_document_tree_async(
        stream,
        file_id=file_id,
        doc_name=str(filename),
        config=config,
    )
    if _is_low_quality_tree(tree=tree, file_id=file_id, pdf_page_count=pdf_page_count):
        raise ValueError(
            f"pageindex_tree_low_quality:file_id={file_id}:pdf_pages={pdf_page_count}"
        )
    return tree


async def _build_tree_from_rag_summary(
    *,
    file_id: str,
    user_id: str,
    session_id: str,
    user_input: str,
) -> Dict[str, Any]:
    rag = await query_knowledge.ainvoke(
        {
            "query": user_input or "Summarize this file by key sections for card generation.",
            "mode": "mix",
            "top_k": 8,
            "session_id": session_id,
            "file_ids": [file_id],
            "user_id": user_id,
        }
    )
    content = _as_str((rag or {}).get("content"))
    refs = (rag or {}).get("refs") if isinstance(rag, dict) else []
    if not content:
        raise ValueError("rag_summary_empty")
    doc_name = file_id
    if isinstance(refs, list) and refs:
        first = refs[0] if isinstance(refs[0], dict) else {}
        doc_name = _as_str(first.get("file_name")) or _as_str(first.get("file_id")) or file_id
    summary = content[:1600]
    return await _summary_to_tree(
        file_id=file_id,
        doc_name=doc_name,
        summary_text=summary,
        user_input=user_input,
    )


def _normalize_outline_node(
    node: Dict[str, Any],
    *,
    fallback_id: str,
    fallback_title: str,
    fallback_summary: str,
) -> Dict[str, Any]:
    children_raw = node.get("nodes") if isinstance(node.get("nodes"), list) else []
    children: List[Dict[str, Any]] = []
    for idx, child in enumerate(children_raw, start=1):
        if not isinstance(child, dict):
            continue
        children.append(
            _normalize_outline_node(
                child,
                fallback_id=f"{fallback_id}{idx}",
                fallback_title=f"Section {idx}",
                fallback_summary=fallback_summary,
            )
        )
    start_index = 1
    end_index = 1
    try:
        start_index = max(1, int(node.get("start_index") or 1))
    except Exception:
        start_index = 1
    try:
        end_index = max(start_index, int(node.get("end_index") or start_index))
    except Exception:
        end_index = start_index
    return {
        "title": _as_str(node.get("title")) or fallback_title,
        "node_id": _as_str(node.get("node_id")) or fallback_id,
        "start_index": start_index,
        "end_index": end_index,
        "summary": _as_str(node.get("summary")) or fallback_summary[:300],
        "nodes": children,
    }


async def _summary_to_tree(
    *,
    file_id: str,
    doc_name: str,
    summary_text: str,
    user_input: str,
) -> Dict[str, Any]:
    system_prompt = (
        "You convert summary text into a hierarchical outline JSON.\n"
        "Output JSON only with schema:\n"
        "{title,node_id,start_index,end_index,summary,nodes:[same schema]}.\n"
        "Use 2-6 first-level nodes, concise summaries."
    )
    user_prompt = (
        f"User request:\n{user_input}\n\n"
        f"Document name:\n{doc_name}\n\n"
        f"Summary:\n{summary_text}"
    )
    raw = ""
    try:
        response = await chat_complete(
            intent="think",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if response and hasattr(response, "choices") and response.choices:
            raw = str(response.choices[0].message.content or "")
    except Exception as exc:
        logger.warning("summary to tree llm failed; using minimal summary tree", error=str(exc))

    parsed = safe_parse_llm_json(raw, default={})
    if not isinstance(parsed, dict):
        parsed = {}
    root = _normalize_outline_node(
        parsed,
        fallback_id="0000",
        fallback_title=doc_name or file_id,
        fallback_summary=summary_text,
    )
    root["title"] = _as_str(root.get("title")) or doc_name or file_id
    root["summary"] = _as_str(root.get("summary")) or summary_text[:300]
    root["file_id"] = file_id
    root["doc_name"] = doc_name or file_id
    root["source"] = "rag_summary"
    if not root.get("nodes"):
        root["nodes"] = [
            {
                "title": "Summary Overview",
                "node_id": "0001",
                "start_index": 1,
                "end_index": 1,
                "summary": summary_text[:400],
                "nodes": [],
            }
        ]
    return root


def _tree_meta(file_id: str, tree: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "file_id": file_id,
        "doc_name": tree.get("doc_name"),
        "title": tree.get("title"),
        "root_node_id": tree.get("node_id"),
        "node_count": len(
            flatten_nodes(
                file_id=file_id,
                doc_name=_as_str(tree.get("doc_name")),
                doc_title=_as_str(tree.get("title") or tree.get("doc_name")),
                nodes=tree.get("nodes") or [],
                include_root=False,
                root=tree,
            )
        ),
        "updated_at": _utc_now(),
        "source": _as_str(tree.get("source")) or "pageindex_tree",
    }


async def build_incremental_document_registry(
    *,
    session_id: str,
    user_id: str,
    file_ids: List[str],
    user_input: str,
    message_knowledge: str,
    conversation_history: List[Dict[str, Any]] | None,
    model: str | None = None,
) -> Dict[str, Any]:
    """Build/update per-file tree JSON registry and return merged view."""
    if not session_id:
        raise ValueError("missing_session_id")
    if not user_id:
        raise ValueError("missing_user_id")

    normalized_file_ids = [fid for fid in (_as_str(x) for x in file_ids) if fid]
    if not normalized_file_ids:
        raise ValueError("missing_file_ids")

    registry = await _load_registry(session_id=session_id, user_id=user_id)
    files = registry.get("files")
    if not isinstance(files, dict):
        files = {}
    registry["files"] = files

    _append_knowledge_history(
        registry,
        _extract_new_knowledge(
            user_input=user_input,
            message_knowledge=message_knowledge,
            conversation_history=conversation_history,
        ),
    )

    failed_files: List[Dict[str, str]] = []
    for file_id in normalized_file_ids:
        if file_id in files and isinstance(files.get(file_id), dict) and files[file_id].get("tree"):
            continue

        try:
            tree = await _build_one_document_tree(file_id=file_id, user_id=user_id, model=model)
        except Exception as exc:
            logger.warning("pageindex tree build failed, trying rag summary", file_id=file_id, error=str(exc))
            try:
                tree = await _build_tree_from_rag_summary(
                    file_id=file_id,
                    user_id=user_id,
                    session_id=session_id,
                    user_input=user_input,
                )
            except Exception as summary_exc:
                failed_files.append({"file_id": file_id, "error": str(summary_exc)})
                continue

        files[file_id] = {
            "tree": tree,
            "meta": _tree_meta(file_id, tree),
        }

    await _save_registry(session_id=session_id, registry=registry)

    ordered_trees: List[Dict[str, Any]] = []
    tree_registry: Dict[str, Dict[str, Any]] = {}
    for file_id in normalized_file_ids:
        item = files.get(file_id)
        if not isinstance(item, dict):
            continue
        tree = item.get("tree")
        meta = item.get("meta")
        if isinstance(tree, dict):
            ordered_trees.append(tree)
        if isinstance(meta, dict):
            tree_registry[file_id] = meta

    return {
        "status": "failed" if failed_files else "success",
        "registry": registry,
        "document_trees": ordered_trees,
        "tree_registry": tree_registry,
        "failed_files": failed_files,
    }
