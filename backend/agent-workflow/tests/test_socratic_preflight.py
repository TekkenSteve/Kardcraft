from __future__ import annotations

import pytest

from kardcraft.workflow.graphs.main_graph import edges, nodes


@pytest.mark.asyncio
async def test_socratic_preflight_skips_when_files_exist():
    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "帮我做卡片",
            "message_knowledge": "",
            "file_ids": ["file_1"],
            "driven_mode": "topic_driven",
            "classification_confidence": 0.2,
        }
    )

    assert result["preflight_status"] == "skipped"
    assert result["preflight_reason"] == "has_files"


@pytest.mark.asyncio
async def test_socratic_preflight_requests_user_input_for_ambiguous_prompt(monkeypatch):
    async def _fake_ainvoke(payload):
        assert payload["user_input"] == "帮我做卡片"
        return {
            "status": "need_user_input",
            "reason": "missing_scope",
            "pending_questions": [
                {
                    "question_id": 1,
                    "question_text": "你想覆盖哪些章节？",
                    "info_type": "scope",
                    "is_required": True,
                    "suggested_answers": [],
                }
            ],
        }

    monkeypatch.setattr(nodes.clarify, "ainvoke", _fake_ainvoke)

    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "帮我做卡片",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "topic_driven",
            "classification_confidence": 0.9,
            "language": "zh",
        }
    )

    assert result["preflight_status"] == "need_user_input"
    assert result["status"] == "need_user_input"
    assert result["question"] == "你想覆盖哪些章节？"
    assert len(result["pending_questions"]) == 1


@pytest.mark.asyncio
async def test_socratic_preflight_passes_through_when_sufficient(monkeypatch):
    async def _fake_ainvoke(payload):
        return {
            "status": "sufficient",
            "reason": "enough_context",
            "pending_questions": [],
        }

    monkeypatch.setattr(nodes.clarify, "ainvoke", _fake_ainvoke)

    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "请按高中代数给我做20张中等难度的卡片",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "content_driven",
            "classification_confidence": 0.95,
            "language": "zh",
        }
    )

    assert result["preflight_status"] == "skipped"
    assert result["preflight_reason"] == "signals_sufficient"


def test_route_after_preflight_routes_to_finalize_on_need_user_input():
    assert edges.route_after_preflight({"preflight_status": "need_user_input"}) == "finalize"
    assert edges.route_after_preflight({"preflight_status": "pass_through"}) == "syllabus_supervisor"
