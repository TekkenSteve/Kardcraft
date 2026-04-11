"""Typed contracts and helpers for local PageIndex integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, TypedDict


class DocumentNode(TypedDict, total=False):
    title: str
    node_id: str
    start_index: int
    end_index: int
    summary: str
    nodes: List["DocumentNode"]


class DocumentTree(TypedDict, total=False):
    file_id: str
    doc_name: str
    doc_description: str
    title: str
    node_id: str
    start_index: int
    end_index: int
    summary: str
    nodes: List[DocumentNode]


class NodeRef(TypedDict, total=False):
    file_id: str
    doc_name: str
    doc_title: str
    title: str
    node_id: str
    start_index: int
    end_index: int
    summary: str
    depth: int
    priority: float


@dataclass(slots=True)
class PageIndexBuildConfig:
    model: Optional[str] = None
    toc_check_page_num: int = 12
    max_page_num_each_node: int = 10
    max_token_num_each_node: int = 60000
    if_add_node_id: str = "yes"
    if_add_node_summary: str = "no"
    if_add_doc_description: str = "no"
    if_add_node_text: str = "no"

    def to_options_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "toc_check_page_num": int(self.toc_check_page_num),
            "max_page_num_each_node": int(self.max_page_num_each_node),
            "max_token_num_each_node": int(self.max_token_num_each_node),
            "if_add_node_id": str(self.if_add_node_id or "yes"),
            "if_add_node_summary": str(self.if_add_node_summary or "no"),
            "if_add_doc_description": str(self.if_add_doc_description or "no"),
            "if_add_node_text": str(self.if_add_node_text or "no"),
        }


def create_node_mapping(nodes: List[DocumentNode]) -> Dict[str, DocumentNode]:
    """Create node_id -> node map."""
    mapping: Dict[str, DocumentNode] = {}
    stack = list(nodes)
    while stack:
        node = stack.pop()
        node_id = str(node.get("node_id") or "").strip()
        if node_id:
            mapping[node_id] = node
        children = node.get("nodes") or []
        if isinstance(children, list):
            stack.extend([c for c in children if isinstance(c, dict)])
    return mapping


def flatten_nodes(
    *,
    file_id: str,
    doc_name: str,
    doc_title: str,
    nodes: List[DocumentNode],
    include_root: bool = False,
    root: Optional[DocumentTree] = None,
) -> List[NodeRef]:
    """Flatten a tree into depth-first node references."""
    flat: List[NodeRef] = []
    if include_root and root:
        flat.append(
            {
                "file_id": file_id,
                "doc_name": doc_name,
                "doc_title": doc_title,
                "title": str(root.get("title") or ""),
                "node_id": str(root.get("node_id") or ""),
                "start_index": int(root.get("start_index") or 1),
                "end_index": int(root.get("end_index") or 1),
                "summary": str(root.get("summary") or ""),
                "depth": 0,
                "priority": 0.0,
            }
        )

    stack: List[tuple[DocumentNode, int]] = [
        (node, 1) for node in reversed([n for n in nodes if isinstance(n, dict)])
    ]
    while stack:
        node, depth = stack.pop()
        flat.append(
            {
                "file_id": file_id,
                "doc_name": doc_name,
                "doc_title": doc_title,
                "title": str(node.get("title") or ""),
                "node_id": str(node.get("node_id") or ""),
                "start_index": int(node.get("start_index") or 1),
                "end_index": int(node.get("end_index") or 1),
                "summary": str(node.get("summary") or ""),
                "depth": depth,
                "priority": 0.0,
            }
        )
        children = node.get("nodes") or []
        for child in reversed([c for c in children if isinstance(c, dict)]):
            stack.append((child, depth + 1))
    return flat


def prune_nodes(nodes: Iterable[NodeRef], *, max_nodes: int, max_depth: int) -> List[NodeRef]:
    out: List[NodeRef] = []
    for node in nodes:
        if len(out) >= max_nodes:
            break
        depth = int(node.get("depth") or 0)
        if depth > max_depth:
            continue
        out.append(node)
    return out
