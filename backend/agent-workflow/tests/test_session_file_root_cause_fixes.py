from __future__ import annotations

import pytest

from kardcraft.ragix.ragix.implementations.preprocessors.parser_router import (
    FileTypeGroup,
    ParserRouter,
)
from kardcraft.ragix.ragix.implementations.parsers.engines.docling import DoclingParser
from kardcraft.workflow.graphs.main_graph.subgraph.syllabus_supervisor_agent import nodes


@pytest.mark.asyncio
async def test_parser_router_routes_pdf_to_docling():
    router = ParserRouter()
    selection = router.select_parser("/tmp/sample.pdf")
    assert selection.group == FileTypeGroup.PDF
    assert selection.parser_cls is DoclingParser


@pytest.mark.asyncio
async def test_syllabus_supervisor_react_does_not_reinvoke_tools(monkeypatch):
    class _SyllabusAgent:
        async def ainvoke(self, payload, context=None):
            assert payload.get("file_ids") == ["file_1"]
            return {
                "learning_units": [],
                "pending_questions": [{"question_id": "q1"}],
                "clarification_responses": {},
            }

    captured = {"tools_len": None}

    async def _run_react_structured(**kwargs):
        captured["tools_len"] = len(kwargs.get("tools") or [])
        return {"status": "need_user_input", "reason": "pending_questions"}

    monkeypatch.setattr(nodes, "syllabus_agent", _SyllabusAgent())
    monkeypatch.setattr(nodes, "run_react_structured", _run_react_structured)

    runtime = type("R", (), {"context": type("C", (), {"session_id": "s1", "user_id": "u1"})()})()
    result = await nodes.run_syllabus_supervisor(
        {
            "user_input": "继续根据文件制卡",
            "message_knowledge": "",
            "file_ids": ["file_1"],
            "subject_domain": "general",
            "task_complexity": "medium",
            "language": "zh",
        },
        runtime=runtime,
    )

    assert captured["tools_len"] == 0
    assert result["status"] == "need_user_input"
