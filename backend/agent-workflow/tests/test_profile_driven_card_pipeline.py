from __future__ import annotations

import pytest

from kardcraft.card_templates import template_selection_service as tss
from kardcraft.workflow.graphs.main_graph.subgraph.card_generation_agent import nodes as cg_nodes
from kardcraft.workflow.graphs.main_graph.subgraph.card_generation_agent import utils as cg_utils
from kardcraft.workflow.graphs.main_graph.subgraph.output_agent import utils as output_utils


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def _tool_stub(fn):
    async def _ainvoke(*args, **kwargs):
        if args:
            return await fn(args[0])
        return await fn(kwargs)

    return type("ToolStub", (), {"ainvoke": staticmethod(_ainvoke)})()


@pytest.mark.asyncio
async def test_run_card_generation_node_quality_consumes_output_cards(monkeypatch):
    captured = {}

    async def _q(payload):
        return {
            "question_drafts": [
                {"id": "c1", "front": "Q1", "question_type": "mcq", "source_unit_id": "u1", "tags": []}
            ]
        }

    async def _a(payload):
        return {"answer_drafts": [{"id": "c1", "answer": "A1", "question_type": "mcq"}]}

    async def _o(payload):
        return {"output_cards": [{"id": "c1", "front": "Q1", "back": "A1", "model": "mcq", "suggested_question_type": "mcq"}]}

    async def _quality(payload):
        captured["cards"] = payload.get("cards")
        return {"approved_cards": payload.get("cards") or [], "quality_report": {}, "refined_cards": payload.get("cards") or []}

    async def _render(payload):
        return {
            "validated_cards": payload.get("cards") or [],
            "render_validation_report": {"checked": len(payload.get("cards") or []), "passed": len(payload.get("cards") or []), "failed": 0},
        }

    monkeypatch.setattr(cg_nodes, "run_question_generation", _tool_stub(_q))
    monkeypatch.setattr(cg_nodes, "run_answer_generation", _tool_stub(_a))
    monkeypatch.setattr(cg_nodes, "output_agent", _tool_stub(_o))
    monkeypatch.setattr(cg_nodes, "render_validation_react_agent", _tool_stub(_render))
    monkeypatch.setattr(cg_nodes, "run_card_quality_pipeline", _tool_stub(_quality))

    result = await cg_nodes.run_card_generation_node(
        {
            "chunk_id": "chunk-1",
            "unit_ids": ["u1"],
            "user_input": "u",
            "message_knowledge": "",
            "subject_domain": "general",
            "query_scope": "focused",
            "learning_units": [{"id": "u1"}],
            "evidence_items": [],
            "document_trees": [],
            "template_profiles": ["mcq"],
            "template_default_profile": "mcq",
            "selected_template_profile": "mcq",
            "profile_prompt_hint": {"resolved_profile": "mcq"},
            "file_ids": [],
        },
        runtime=type("R", (), {"context": None})(),
    )

    assert result["approved_cards"]
    assert captured["cards"][0]["id"] == "c1"
    assert captured["cards"][0]["front"] == "Q1"
    assert captured["cards"][0]["back"] == "A1"
    assert captured["cards"][0]["model"] == "mcq"
    assert captured["cards"][0]["suggested_question_type"] == "mcq"


@pytest.mark.asyncio
async def test_output_generation_injects_selected_profile_hint(monkeypatch):
    captured = {}

    async def _fake_chat_complete(*, intent, temperature, messages):
        del intent, temperature
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return _FakeResponse(
            '{"cards":[{"id":"c1","front":"Final Q","back":"Final A","model":"mcq","suggested_question_type":"mcq","source_unit_id":"u1","tags":["t1"]}]}'
        )

    monkeypatch.setattr(output_utils, "chat_complete", _fake_chat_complete)

    result = await output_utils.run_output_generation.ainvoke(
        {
            "cards": [{"id": "c1", "front": "Question?", "back": "Answer.", "model": "mcq", "suggested_question_type": "mcq", "source_unit_id": "u1", "tags": ["t1"]}],
            "payload": {
                "template_profiles": ["mcq", "cloze"],
                "selected_template_profile": "mcq",
                "profile_prompt_hint": {
                    "requested_profile": "mcq",
                    "resolved_profile": "mcq",
                    "resolution": "selected",
                    "sample_fields": {"Front": "F", "Back": "B", "Tags": "k::mcq"},
                    "field_order": ["Front", "Back", "Tags"],
                },
            },
        }
    )

    assert "selected_question_type" in captured["user"]
    assert "profile_prompt_hint" in captured["user"]
    assert result["output_cards"][0]["model"] == "mcq"
    assert result["output_cards"][0]["suggested_question_type"] == "mcq"


@pytest.mark.asyncio
async def test_quality_gate_reports_question_type_mismatch(monkeypatch):
    async def _always_approve(*args, **kwargs):
        del args, kwargs
        return {"c1": {"decision": "approve", "score": 0.9, "reason_codes": []}}

    async def _no_principles(*args, **kwargs):
        del args, kwargs
        return ""

    monkeypatch.setattr(cg_utils, "_soft_judge_with_llm", _always_approve)
    monkeypatch.setattr(cg_utils, "_format_principles_for_prompt", _no_principles)

    result = await cg_utils._quality_gate_with_llm(
        [{"id": "c1", "front": "Q", "back": "A", "model": "cloze", "suggested_question_type": "cloze"}],
        query_scope="focused",
        document_titles=[],
        subject_domain="general",
        expected_question_type="mcq",
    )

    assert result["approved_cards"] == []
    failed = result["quality_report"]["failed_cards"]
    assert failed and "hard_question_type_mismatch" in failed[0]["reason_codes"]
    assert result["quality_report"]["reason_code_counts"]["hard_question_type_mismatch"] == 1


def test_profile_sample_fields_resolution_and_compact_hint():
    mapping_spec = {
        "profiles": [
            {
                "name": "mcq",
                "sample_fields": {
                    "Front": "Front example",
                    "Back": "Back example",
                    "Tags": "kard::mcq",
                },
            }
        ]
    }

    resolved_profile, sample_fields, resolution = tss._resolve_profile_sample_fields(
        mapping_spec=mapping_spec,
        requested_profile="cloze",
        default_profile="mcq",
    )
    hint = tss._build_profile_prompt_hint(
        requested_profile="cloze",
        resolved_profile=resolved_profile,
        sample_fields=sample_fields,
        resolution=resolution,
    )

    assert resolved_profile == "mcq"
    assert resolution == "fallback"
    assert hint["requested_profile"] == "cloze"
    assert hint["resolved_profile"] == "mcq"
    assert hint["sample_fields"]["Front"] == "Front example"
