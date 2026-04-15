"""Nodes for render validation ReAct agent."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
from langgraph.runtime import Runtime

from kardcraft.db import CardTemplateRepository
from kardcraft.llm.client import chat_complete
from kardcraft.utils.llm_json import safe_parse_llm_json
from kardcraft.utils.logger import logger
from kardcraft.workflow.graphs.main_graph.state import Context

from .state import State

ANKI_RUNTIME_URL = os.getenv("ANKI_RUNTIME_URL", "http://anki-runtime:8012").rstrip("/")


def _safe_profile_prompt_hint(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("profile_prompt_hint")
    if not isinstance(raw, dict):
        return {}
    sample_fields = raw.get("sample_fields") if isinstance(raw.get("sample_fields"), dict) else {}
    return {
        "requested_profile": str(raw.get("requested_profile") or "").strip(),
        "resolved_profile": str(raw.get("resolved_profile") or "").strip(),
        "resolution": str(raw.get("resolution") or "").strip(),
        "sample_fields": {str(k): str(v) for k, v in sample_fields.items() if str(k).strip()},
    }


def _selected_profile(payload: Dict[str, Any]) -> str:
    hint = _safe_profile_prompt_hint(payload)
    resolved = str(hint.get("resolved_profile") or "").strip()
    if resolved:
        return resolved
    selected = str(payload.get("selected_template_profile") or "").strip()
    if selected:
        return selected
    default_profile = str(payload.get("template_default_profile") or "").strip()
    return default_profile or "default"


async def _load_template_bundle(
    *,
    user_id: str,
    template_id: str,
    template_version: int,
) -> Any:
    repo = CardTemplateRepository()
    return await repo.get_accessible_active_template(
        template_id=template_id,
        user_id=user_id,
        version=template_version,
    )


def _build_sample_fields(card: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    hint = _safe_profile_prompt_hint(payload)
    sample_fields = dict(hint.get("sample_fields") or {})
    if "Front" not in sample_fields:
        sample_fields["Front"] = str(card.get("front") or "")
    else:
        sample_fields["Front"] = str(card.get("front") or sample_fields["Front"] or "")
    if "Back" not in sample_fields:
        sample_fields["Back"] = str(card.get("back") or "")
    else:
        sample_fields["Back"] = str(card.get("back") or sample_fields["Back"] or "")
    return sample_fields


async def _preview_card(
    *,
    card: Dict[str, Any],
    payload: Dict[str, Any],
    template_bundle: Any,
    selected_profile: str,
) -> Dict[str, Any]:
    req_payload = {
        "template_id": str(template_bundle.template_id or ""),
        "version": int(template_bundle.version or 1),
        "front_html": str(template_bundle.front_html or ""),
        "back_html": str(template_bundle.back_html or ""),
        "css": str(template_bundle.css or ""),
        "js": template_bundle.js,
        "sample_fields": _build_sample_fields(card, payload),
        "mapping_spec": template_bundle.mapping_spec if isinstance(template_bundle.mapping_spec, dict) else {},
        "template_profile": selected_profile,
        "preview_mode": "safe",
        "strict_validation": True,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{ANKI_RUNTIME_URL}/internal/anki/preview", json=req_payload)
    if resp.status_code >= 400:
        detail = {}
        try:
            detail = resp.json().get("detail", {}) if isinstance(resp.json(), dict) else {}
        except Exception:
            detail = {"message": resp.text}
        validation = detail.get("validation") if isinstance(detail, dict) else {}
        if not isinstance(validation, dict):
            validation = {"ok": False, "errors": [detail], "warnings": []}
        return {"ok": False, "validation": validation}
    payload_resp = resp.json() if resp.content else {}
    validation = payload_resp.get("validation") if isinstance(payload_resp, dict) else {}
    if not isinstance(validation, dict):
        validation = {"ok": True, "errors": [], "warnings": []}
    return {"ok": bool(validation.get("ok", True)), "validation": validation}


async def _repair_card_with_llm(
    *,
    card: Dict[str, Any],
    payload: Dict[str, Any],
    selected_profile: str,
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    system_prompt = (
        "You are a flashcard render-fix agent in a ReAct loop. "
        "Given validation errors from template preview, repair only front/back to make the card render-valid. "
        "Return JSON only: {\"front\": str, \"back\": str}."
    )
    user_prompt = {
        "selected_question_type": selected_profile,
        "profile_prompt_hint": _safe_profile_prompt_hint(payload),
        "card": {"id": card.get("id"), "front": card.get("front"), "back": card.get("back")},
        "validation": validation,
    }
    try:
        response = await chat_complete(
            intent="reasoning",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(user_prompt)},
            ],
        )
        content = ""
        if response and getattr(response, "choices", None):
            content = getattr(response.choices[0].message, "content", "") or ""
        parsed = safe_parse_llm_json(content, default={})
        front = str(parsed.get("front") or "").strip() if isinstance(parsed, dict) else ""
        back = str(parsed.get("back") or "").strip() if isinstance(parsed, dict) else ""
        if front and back:
            fixed = dict(card)
            fixed["front"] = front
            fixed["back"] = back
            return fixed
    except Exception:
        pass
    return card


async def run_render_validation_react_node(
    state: State,
    runtime: Runtime[Context],
) -> Dict[str, Any]:
    cards = [item for item in (state.get("cards") or []) if isinstance(item, dict)]
    payload = dict(state.get("payload") or {})
    if not cards:
        return {
            "validated_cards": [],
            "render_validation_report": {"checked": 0, "passed": 0, "failed": 0, "attempts": 0, "status": "no_cards"},
        }

    template_id = str(payload.get("template_id") or "").strip()
    try:
        template_version = int(payload.get("template_version") or 0)
    except Exception:
        template_version = 0
    user_id = str((runtime.context.user_id if runtime and runtime.context else "") or "").strip()
    selected_profile = _selected_profile(payload)
    max_rounds = 3

    if not template_id or not user_id:
        return {
            "validated_cards": cards,
            "render_validation_report": {
                "checked": len(cards),
                "passed": len(cards),
                "failed": 0,
                "attempts": 0,
                "status": "skipped_missing_template_context",
            },
        }

    template_bundle = await _load_template_bundle(
        user_id=user_id,
        template_id=template_id,
        template_version=template_version,
    )
    if template_bundle is None:
        return {
            "validated_cards": cards,
            "render_validation_report": {
                "checked": len(cards),
                "passed": len(cards),
                "failed": 0,
                "attempts": 0,
                "status": "skipped_template_not_found",
            },
        }

    validated_cards: List[Dict[str, Any]] = []
    failed_cards: List[Dict[str, Any]] = []
    attempts = 0

    for raw_card in cards:
        current = dict(raw_card)
        last_validation: Dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
        passed = False
        for _ in range(max_rounds):
            attempts += 1
            observation = await _preview_card(
                card=current,
                payload=payload,
                template_bundle=template_bundle,
                selected_profile=selected_profile,
            )
            validation = observation.get("validation") if isinstance(observation, dict) else {}
            if not isinstance(validation, dict):
                validation = {"ok": False, "errors": [{"code": "invalid_validation_payload"}], "warnings": []}
            last_validation = validation
            if bool(observation.get("ok")):
                passed = True
                break
            current = await _repair_card_with_llm(
                card=current,
                payload=payload,
                selected_profile=selected_profile,
                validation=validation,
            )
        if passed:
            validated_cards.append(current)
        else:
            failed_cards.append(
                {
                    "card": current,
                    "validation": last_validation,
                    "reason_code": "render_validation_failed",
                }
            )

    logger.info(
        "render validation react summary",
        checked=len(cards),
        passed=len(validated_cards),
        failed=len(failed_cards),
        attempts=attempts,
        template_id=template_id,
        selected_profile=selected_profile,
    )
    return {
        "validated_cards": validated_cards,
        "render_validation_report": {
            "checked": len(cards),
            "passed": len(validated_cards),
            "failed": len(failed_cards),
            "attempts": attempts,
            "failed_cards": failed_cards,
            "status": "completed",
        },
    }
