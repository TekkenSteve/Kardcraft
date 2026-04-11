"""Prompt builders for main graph retrieval and planning."""

from __future__ import annotations

from typing import Any, Dict, List


def build_node_query(user_input: str, node: Dict[str, Any], *, include_user_input: bool = True) -> str:
    title = str(node.get("title") or "").strip()
    summary = str(node.get("summary") or "").strip()
    doc_title = str(node.get("doc_title") or node.get("doc_name") or "").strip()
    file_id = str(node.get("file_id") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    demand = str(user_input or "").strip()
    topic = title or summary or "Current outline node"
    lines: List[str] = []
    lines.append("Task: extract testable knowledge for flashcard generation.")
    if doc_title:
        lines.append(f"Document: {doc_title}")
    if file_id:
        lines.append(f"File ID: {file_id}")
    if node_id:
        lines.append(f"Node ID: {node_id}")
    lines.append(f"Outline node: {topic}")
    if include_user_input and demand:
        lines.append(f"User objective: {demand}")
    if summary:
        lines.append(f"Node summary: {summary}")
    lines.append("Extract from the file:")
    lines.append("1) Core concepts, definitions, rules, and procedures")
    lines.append("2) Boundary conditions, pitfalls, and counterexamples")
    lines.append("3) Testable facts and contrasts that can become cards")
    lines.append("Output requirements: keep only node-relevant knowledge and include traceable source snippets.")
    return "\n".join(lines)
