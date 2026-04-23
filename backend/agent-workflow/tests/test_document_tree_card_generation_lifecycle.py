from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kardcraft.utils import document_registry
from kardcraft.workflow.graphs.main_graph.subgraph.card_generation_agent import nodes as cg_nodes


def _tool_stub(fn):
    async def _ainvoke(*args, **kwargs):
        if args:
            return await fn(args[0])
        return await fn(kwargs)

    return type("ToolStub", (), {"ainvoke": staticmethod(_ainvoke)})()


@pytest.mark.asyncio
async def test_document_tree_driven_card_generation_has_no_pending_task_warning(monkeypatch):
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    loop_contexts: list[dict] = []

    def _capture_exception_handler(_loop, context):
        loop_contexts.append(context)
        if original_handler is not None:
            original_handler(_loop, context)

    loop.set_exception_handler(_capture_exception_handler)
    try:
        async def _fake_download_conversation_file(*, user_id, file_id):
            assert user_id == "user-1"
            assert file_id == "file-1"
            metadata = SimpleNamespace(custom_meta={"original_filename": "lecture.pdf"})
            return b"raw-bytes", metadata

        async def _fake_build_document_tree_async(file_obj, *, file_id, doc_name, config):
            assert hasattr(file_obj, "read")
            assert file_id == "file-1"
            assert doc_name == "lecture.pdf"
            assert config is not None
            return {
                "file_id": file_id,
                "doc_name": doc_name,
                "title": "Lecture",
                "node_id": "0000",
                "start_index": 1,
                "end_index": 2,
                "summary": "Doc",
                "nodes": [
                    {
                        "title": "Section A",
                        "node_id": "0001",
                        "start_index": 1,
                        "end_index": 1,
                        "summary": "A",
                    }
                ],
            }

        async def _q(input_payload):
            payload = input_payload.get("payload") if isinstance(input_payload, dict) else {}
            assert isinstance(payload, dict)
            assert payload.get("document_trees")
            return {
                "question_drafts": [
                    {
                        "id": "c1",
                        "front": "Q1",
                        "question_type": "mcq",
                        "source_unit_id": "file-1:0001",
                        "tags": [],
                    }
                ]
            }

        async def _a(_payload):
            return {"answer_drafts": [{"id": "c1", "answer": "A1", "question_type": "mcq"}]}

        async def _o(_payload):
            return {
                "output_cards": [
                    {
                        "id": "c1",
                        "front": "Q1",
                        "back": "A1",
                        "model": "mcq",
                        "suggested_question_type": "mcq",
                        "source_unit_id": "file-1:0001",
                    }
                ]
            }

        async def _quality(payload):
            cards = payload.get("cards") or []
            return {"approved_cards": cards, "quality_report": {}, "refined_cards": cards}

        async def _render(payload):
            cards = payload.get("cards") or []
            return {
                "validated_cards": cards,
                "render_validation_report": {
                    "checked": len(cards),
                    "passed": len(cards),
                    "failed": 0,
                },
            }

        monkeypatch.setattr(document_registry, "download_conversation_file", _fake_download_conversation_file)
        monkeypatch.setattr(document_registry, "build_document_tree_async", _fake_build_document_tree_async)
        monkeypatch.setattr(document_registry, "_convert_to_pdf_bytes", lambda file_bytes, metadata: b"%PDF-1.4")
        monkeypatch.setattr(document_registry, "_count_pdf_pages", lambda pdf_bytes: 2)
        monkeypatch.setattr(document_registry, "_is_low_quality_tree", lambda **kwargs: False)

        tree = await document_registry._build_one_document_tree(
            file_id="file-1",
            user_id="user-1",
            model="openai/gpt-4o-mini",
        )
        assert tree["file_id"] == "file-1"
        assert tree["nodes"][0]["node_id"] == "0001"

        monkeypatch.setattr(cg_nodes, "run_question_generation", _tool_stub(_q))
        monkeypatch.setattr(cg_nodes, "run_answer_generation", _tool_stub(_a))
        monkeypatch.setattr(cg_nodes, "output_agent", _tool_stub(_o))
        monkeypatch.setattr(cg_nodes, "render_validation_react_agent", _tool_stub(_render))
        monkeypatch.setattr(cg_nodes, "run_card_quality_pipeline", _tool_stub(_quality))

        result = await cg_nodes.run_card_generation_node(
            {
                "chunk_id": "scope_1",
                "unit_ids": ["file-1:0001"],
                "user_input": "Generate cards",
                "message_knowledge": "",
                "subject_domain": "general",
                "query_scope": "focused",
                "learning_units": [{"id": "file-1:0001", "title": "Section A"}],
                "evidence_items": [
                    {
                        "content": "Section A content",
                        "node": {"file_id": "file-1", "node_id": "0001", "title": "Section A"},
                    }
                ],
                "document_trees": [tree],
                "template_profiles": ["mcq"],
                "template_default_profile": "mcq",
                "selected_template_profile": "mcq",
                "profile_prompt_hint": {"resolved_profile": "mcq"},
                "file_ids": ["file-1"],
            },
            runtime=type("R", (), {"context": None})(),
        )

        assert len(result["approved_cards"]) == 1
        lifecycle_messages = [str(ctx.get("message") or "") for ctx in loop_contexts]
        assert not any("Task was destroyed but it is pending" in message for message in lifecycle_messages)
    finally:
        loop.set_exception_handler(original_handler)
