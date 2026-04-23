"""Stable document tree API built on local page_index core."""

from __future__ import annotations

import contextlib
import io
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from .contracts import DocumentNode, DocumentTree, PageIndexBuildConfig
from .page_index import page_index_main_async


def _normalize_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _coerce_index(value: Any, fallback: int) -> int:
    try:
        number = int(value)
        return number if number > 0 else fallback
    except Exception:
        return fallback


def _normalize_nodes(
    nodes: Any,
    *,
    seq: List[int],
) -> List[DocumentNode]:
    if not isinstance(nodes, list):
        return []
    normalized: List[DocumentNode] = []
    for item in nodes:
        if not isinstance(item, dict):
            continue
        seq[0] += 1
        node_id = _normalize_text(item.get("node_id"), fallback=f"{seq[0]:04d}")
        title = _normalize_text(item.get("title"), fallback=f"Section {seq[0]}")
        start_index = _coerce_index(item.get("start_index"), fallback=1)
        end_index = _coerce_index(item.get("end_index"), fallback=start_index)
        summary = _normalize_text(item.get("summary"), fallback=f"{title} ({start_index}-{end_index})")
        children = _normalize_nodes(item.get("nodes"), seq=seq)
        node: DocumentNode = {
            "title": title,
            "node_id": node_id,
            "start_index": start_index,
            "end_index": max(start_index, end_index),
            "summary": summary,
        }
        if children:
            node["nodes"] = children
        normalized.append(node)
    return normalized


def _compute_index_bounds(nodes: List[DocumentNode]) -> tuple[int, int]:
    if not nodes:
        return 1, 1
    start = min(int(node.get("start_index") or 1) for node in nodes)
    end = max(int(node.get("end_index") or start) for node in nodes)
    return start, max(start, end)


def _to_document_tree(raw: Dict[str, Any], *, file_id: str) -> DocumentTree:
    doc_name = _normalize_text(raw.get("doc_name"), fallback=file_id)
    title = _normalize_text(raw.get("doc_name"), fallback="Document")
    doc_description = _normalize_text(raw.get("doc_description"))
    seq = [0]
    child_nodes = _normalize_nodes(raw.get("structure"), seq=seq)
    start_index, end_index = _compute_index_bounds(child_nodes)
    root_summary = doc_description or f"Document title: {title}"
    tree: DocumentTree = {
        "file_id": file_id,
        "doc_name": doc_name,
        "doc_description": doc_description,
        "title": title,
        "node_id": "0000",
        "start_index": start_index,
        "end_index": end_index,
        "summary": root_summary,
        "nodes": child_nodes,
    }
    return tree


def _build_options(config: PageIndexBuildConfig | None) -> SimpleNamespace:
    cfg = config or PageIndexBuildConfig()
    return SimpleNamespace(**cfg.to_options_dict())


async def build_document_tree_async(
    file_obj: str | Path | BytesIO,
    *,
    file_id: str,
    doc_name: str | None = None,
    config: PageIndexBuildConfig | None = None,
) -> DocumentTree:
    """Build a normalized document tree for one file."""
    # page_index_main still contains legacy prints; silence stdout for workflow usage.
    with contextlib.redirect_stdout(io.StringIO()):
        raw = await page_index_main_async(file_obj, _build_options(config), doc_name=doc_name)
    if not isinstance(raw, dict):
        raise ValueError("page_index_main returned invalid payload")
    return _to_document_tree(raw, file_id=file_id)
