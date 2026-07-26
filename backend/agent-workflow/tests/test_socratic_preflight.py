from __future__ import annotations

import pytest

from kardcraft.workflow.graphs.main_graph import edges, nodes


def _runtime(session_id: str = "s_test", user_id: str = "u_test"):
    return type(
        "R",
        (),
        {"context": type("C", (), {"session_id": session_id, "user_id": user_id})()},
    )()


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
        },
        runtime=_runtime(),
    )

    assert result["preflight_status"] == "skipped"
    assert result["preflight_reason"] == "has_files"


@pytest.mark.asyncio
async def test_socratic_preflight_requests_user_input_for_ambiguous_prompt(monkeypatch):
    async def _fake_ainvoke(_tool, payload, *args, **kwargs):
        assert payload["user_input"] == "帮我做卡片"
        return {
            "status": "need_user_input",
            "reason": "missing_scope",
            "pending_questions": [
                {
                    "id": "q_scope_1",
                    "question_text": "你想覆盖哪些章节？",
                    "info_type": "scope",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            ],
        }

    monkeypatch.setattr(type(nodes.clarify), "ainvoke", _fake_ainvoke)

    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "帮我做卡片",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "topic_driven",
            "classification_confidence": 0.9,
            "language": "zh",
        },
        runtime=_runtime(),
    )

    assert result["preflight_status"] == "need_user_input"
    assert result["status"] == "need_user_input"
    assert result["clarification_state"] == "collecting"
    assert result["question"] == "你想覆盖哪些章节？"
    assert len(result["pending_questions"]) == 1


@pytest.mark.asyncio
async def test_socratic_preflight_passes_through_when_sufficient(monkeypatch):
    async def _fake_ainvoke(_tool, payload, *args, **kwargs):
        return {
            "status": "success",
            "reason": "enough_context",
            "pending_questions": [],
        }

    monkeypatch.setattr(type(nodes.clarify), "ainvoke", _fake_ainvoke)

    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "请按高中代数给我做20张中等难度的卡片",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "content_driven",
            "classification_confidence": 0.95,
            "language": "zh",
        },
        runtime=_runtime(),
    )

    assert result["preflight_status"] == "skipped"
    assert result["preflight_reason"] == "signals_sufficient"


def test_route_after_preflight_routes_to_finalize_on_need_user_input():
    assert edges.route_after_preflight({"preflight_status": "need_user_input"}) == "finalize"
    assert edges.route_after_preflight({"preflight_status": "pass_through"}) == "syllabus_supervisor"


@pytest.mark.asyncio
async def test_socratic_preflight_rejects_unknown_response_keys():
    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "帮我做卡片",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "topic_driven",
            "classification_confidence": 0.2,
            "clarification_round": 1,
            "pending_questions": [
                {
                    "id": "q_scope_1",
                    "question_text": "你想覆盖哪些章节？",
                    "info_type": "scope",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            ],
            "clarification_responses": {"q_unknown": "函数与极限"},
        },
        runtime=_runtime(),
    )

    assert result["status"] == "failed"
    assert result["termination_reason"] == "invalid_clarification_response_keys"


@pytest.mark.asyncio
async def test_socratic_preflight_marks_exhausted_when_round_limit_reached(monkeypatch):
    async def _fake_ainvoke(_tool, payload, *args, **kwargs):
        return {
            "status": "need_user_input",
            "reason": "still_missing_scope",
            "pending_questions": [
                {
                    "id": "q_scope_2",
                    "question_text": "请明确你希望覆盖的知识边界。",
                    "info_type": "scope",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            ],
        }

    monkeypatch.setattr(type(nodes.clarify), "ainvoke", _fake_ainvoke)

    result = await nodes.run_socratic_preflight(
        {
            "intent_type": "create_cards",
            "user_input": "继续",
            "message_knowledge": "",
            "file_ids": [],
            "driven_mode": "topic_driven",
            "classification_confidence": 0.2,
            "clarification_round": 3,
            "max_rounds": 3,
            "pending_questions": [
                {
                    "id": "q_scope_1",
                    "question_text": "你想覆盖哪些章节？",
                    "info_type": "scope",
                    "required": True,
                    "input_type": "free_text",
                    "options": [],
                }
            ],
            "clarification_responses": {"q_scope_1": "函数与极限"},
        },
        runtime=_runtime(),
    )

    assert result["status"] == "need_user_input"
    assert result["clarification_state"] == "exhausted"
    assert result["termination_reason"] == "exhausted"
