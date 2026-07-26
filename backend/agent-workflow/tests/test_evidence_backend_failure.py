from __future__ import annotations

import pytest

from kardcraft.workflow.graphs.main_graph.subgraph.evidence_react_agent import nodes
from kardcraft.workflow.graphs.main_graph.subgraph.evidence_react_agent import tools


@pytest.mark.asyncio
async def test_evidence_backend_error_fails_instead_of_requesting_user_input(monkeypatch):
    async def _failed_query(_payload):
        return {
            "content": "",
            "refs": [],
            "error": "failed to index requested files: file-1: parser failed",
            "diagnostics": {"backend_error": True, "error_type": "FileIndexingError"},
        }

    query_stub = type("QueryStub", (), {"ainvoke": staticmethod(_failed_query)})()
    monkeypatch.setattr(tools, "query_knowledge", query_stub)

    async def _run_react(**_kwargs):
        return None

    monkeypatch.setattr(nodes, "run_react_structured", _run_react)
    runtime = type(
        "Runtime",
        (),
        {"context": type("Context", (), {"session_id": "session-1", "user_id": "user-1"})()},
    )()

    result = await nodes.run_evidence_react_node(
        {
            "candidate_nodes": [
                {
                    "node_id": "0001",
                    "title": "Section One",
                    "summary": "Grounded section summary",
                }
            ],
            "query_scope": "title_only",
            "retrieval_budget": {
                "max_nodes_per_round": 1,
                "max_rag_calls": 1,
                "min_information_gain": 0.03,
                "consecutive_low_gain_limit": 1,
            },
            "file_ids": ["file-1"],
            "user_input": "Create cards",
        },
        runtime,
    )

    assert result["status"] == "failed"
    assert result["evidence_status"] == "failed"
    assert result["pending_questions"] == []
    assert result["termination_reason"] == "backend_error"
    assert result["error"].startswith("knowledge_retrieval_failed:")
