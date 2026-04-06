from __future__ import annotations

import pytest

from kardcraft.workflow.graphs.main_graph.subgraph.evidence_supervisor_agent import nodes


class _FakeTool:
    def __init__(self, handler):
        self._handler = handler

    async def ainvoke(self, payload):
        return await self._handler(payload)


@pytest.mark.asyncio
async def test_lazy_index_and_retry_ragix_recovers_after_reindex(monkeypatch):
    async def _list_history_files(payload):
        return {
            "files": [
                {"file_id": "f_hist_1"},
                {"file_id": "f_hist_2"},
            ]
        }

    async def _index_file_to_ragix(payload):
        return {"status": "indexed", "track_id": f"track-{payload.get('file_id')}"}

    call_count = {"n": 0}

    async def _query_ragix_evidence(payload):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"content": ""}
        return {"content": "recovered by lazy index", "refs": []}

    monkeypatch.setattr(nodes, "list_history_files", _FakeTool(_list_history_files))
    monkeypatch.setattr(nodes, "index_file_to_ragix", _FakeTool(_index_file_to_ragix))
    monkeypatch.setattr(nodes, "query_ragix_evidence", _FakeTool(_query_ragix_evidence))

    result = await nodes.lazy_index_and_retry_ragix.ainvoke(
        {
            "query": "help me make cards",
            "top_k": 8,
            "session_id": "s1",
            "file_ids": [],
            "user_id": "u1",
            "max_retries": 2,
        }
    )

    assert result["content"] == "recovered by lazy index"
    assert result["attempts"] >= 1
    assert "f_hist_1" in result["indexed_file_ids"]

