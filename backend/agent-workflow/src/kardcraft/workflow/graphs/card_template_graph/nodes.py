"""Nodes for dedicated card template workflow."""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from kardcraft.db import CardTemplateRepository
from kardcraft.utils.logger import logger

from .state import CardTemplateState

FALLBACK_FRONT_TEMPLATE = (
    '<div class="kardcraft-card"><div class="front">{{Front}}</div></div>'
)
FALLBACK_BACK_TEMPLATE = (
    '<div class="kardcraft-card"><div class="front">{{Front}}</div>'
    '<hr><div class="back">{{Back}}</div></div>'
)
FALLBACK_STYLE = (
    ".kardcraft-card{font-family:Georgia,serif;padding:12px}"
    ".front{font-size:1.2em}.back{margin-top:10px}"
)
ANKI_RUNTIME_URL = os.getenv("ANKI_RUNTIME_URL", "http://anki-runtime:8012").rstrip("/")


def initialize_template_flow(state: CardTemplateState) -> Dict[str, Any]:
    """Prepare defaults for card template generation flow."""
    template_id = state.get("template_id")
    render_target = state.get("render_target") or "anki"

    logger.info(
        "🧩 card_template_graph initialized",
        user_id=state.get("user_id"),
        session_id=state.get("session_id"),
        template_id=template_id,
        render_target=render_target,
    )

    return {
        "template_id": template_id,
        "template_version": state.get("template_version"),
        "render_target": render_target,
    }


async def load_template_bundle(state: CardTemplateState) -> Dict[str, Any]:
    """
    Load template assets and extract Anki field information.
    This graph is intentionally decoupled from main_graph and deep_research_agent.
    """
    template_id = state.get("template_id")
    template_version = state.get("template_version")
    render_target = state.get("render_target") or "anki"

    try:
        user_id = state.get("user_id") or ""
        record = None
        if template_id:
            version = int(template_version or 0)
            repository = CardTemplateRepository()
            record = await repository.get_accessible_active_template(
                template_id=template_id,
                user_id=user_id,
                version=version,
            )

        if record is None:
            return {
                "template_bundle": {
                    "template_id": template_id or "kardcraft-fallback",
                    "template_version": template_version or 1,
                    "render_target": render_target,
                    "source": "builtin:fallback",
                    "front_template": FALLBACK_FRONT_TEMPLATE,
                    "back_template": FALLBACK_BACK_TEMPLATE,
                    "css": FALLBACK_STYLE,
                    "js": None,
                    "mapping_spec": {},
                }
            }

        return {
            "template_bundle": {
                "template_id": str(record.template_id),
                "template_version": int(record.version),
                "render_target": render_target,
                "source": str(record.source),
                "front_template": str(record.front_html),
                "back_template": str(record.back_html),
                "css": str(record.css),
                "js": record.js,
                "mapping_spec": record.mapping_spec or {},
            }
        }
    except Exception as exc:
        logger.error("❌ failed to load template bundle", error=str(exc))
        return {
            "status": "failed",
            "error": f"failed_to_load_template: {exc}",
        }


def build_template_blueprint(state: CardTemplateState) -> Dict[str, Any]:
    """Build final template payload that can be consumed by Anki adapters."""
    if state.get("error"):
        return {
            "status": "failed",
            "output": f"Template workflow failed: {state.get('error')}",
        }

    topic = (state.get("topic") or "").strip()
    template_bundle = state.get("template_bundle") or {}
    template_id = template_bundle.get("template_id") or state.get("template_id") or "kardcraft-fallback"
    template_version = template_bundle.get("template_version") or state.get("template_version") or 1
    render_target = template_bundle.get("render_target") or state.get("render_target") or "anki"
    file_ids = state.get("file_ids") or []
    input_payload = state.get("input") or {}
    context_payload = input_payload.get("context") or {}
    user_fields = context_payload.get("template_fields")
    if not isinstance(user_fields, dict):
        user_fields = {}

    try:
        front_template = (template_bundle or {}).get("front_template", "")
        back_template = (template_bundle or {}).get("back_template", "")
        css = (template_bundle or {}).get("css", "")
        js = (template_bundle or {}).get("js")
        mapping_spec = (template_bundle or {}).get("mapping_spec") or {}
        source = (template_bundle or {}).get("source", "unknown")

        sample_fields: dict[str, Any] = {}
        sample_fields.update(user_fields)
        if "Front" not in sample_fields:
            sample_fields["Front"] = topic or "Template Preview"
        if "Back" not in sample_fields:
            sample_fields["Back"] = (
                f"Template preview for: {topic}" if topic else "Template preview"
            )
        if "Deck" not in sample_fields:
            sample_fields["Deck"] = "Kardcraft::Generated"
        if "Tags" not in sample_fields:
            sample_fields["Tags"] = "kardcraft::template_preview"

        req_payload = {
            "template_id": template_id,
            "version": template_version,
            "front_html": front_template,
            "back_html": back_template,
            "css": css,
            "js": js,
            "sample_fields": sample_fields,
            "mapping_spec": mapping_spec,
            "preview_mode": "high_fidelity",
            "strict_validation": bool(context_payload.get("strict_template_validation")),
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{ANKI_RUNTIME_URL}/internal/anki/preview",
                json=req_payload,
            )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(
                f"anki runtime preview failed ({resp.status_code}): {resp.text}"
            )
        render = resp.json()
        validation = render.get("validation") or {}
        validation_errors = validation.get("errors") or []
        validation_warnings = validation.get("warnings") or render.get("warnings") or []
        engine_used = str(render.get("engine_used") or "unknown")
        engine_fallback = bool(render.get("engine_fallback"))
        note_fields = list(render.get("note_fields") or [])
        if "Front" not in note_fields:
            note_fields.append("Front")
        if "Back" not in note_fields:
            note_fields.append("Back")
        payload = {
            "render_target": render_target,
            "template": {
                "template_id": template_id,
                "template_version": template_version,
                "source": source,
                "fields_detected": render.get("note_fields") or [],
                "engine_used": engine_used,
                "engine_fallback": engine_fallback,
            },
            "note_type": {
                "name": f"Kardcraft::{template_id}",
                "fields": note_fields,
                "templates": [
                    {
                        "name": "Card 1",
                        "qfmt": front_template,
                        "afmt": back_template,
                    }
                ],
                "css": css,
            },
            "preview": {
                "fields": sample_fields,
                "front_html": render.get("front_html_rendered", ""),
                "back_html": render.get("back_html_rendered", ""),
                "validation": {
                    "ok": bool(validation.get("ok", True)),
                    "errors": validation_errors,
                    "warnings": validation_warnings,
                },
            },
        }
    except Exception as exc:
        logger.error("❌ failed to build anki payload", error=str(exc))
        return {
            "status": "failed",
            "error": f"failed_to_build_anki_payload: {exc}",
            "output": f"Template workflow failed: {exc}",
        }

    blueprint = {
        "mode": "card_template",
        "template_id": template_id,
        "template_version": template_version,
        "render_target": render_target,
        "template_source": (template_bundle or {}).get("source", "unknown"),
        "user_requirement": topic,
        "input_file_count": len(file_ids),
        "anki_note_fields": payload["note_type"]["fields"],
        "detected_fields": payload["template"]["fields_detected"],
        "engine_used": payload["template"]["engine_used"],
        "engine_fallback": payload["template"]["engine_fallback"],
        "validation_ok": payload["preview"]["validation"]["ok"],
        "validation_error_count": len(payload["preview"]["validation"]["errors"]),
        "validation_warning_count": len(payload["preview"]["validation"]["warnings"]),
        "sections": [
            "note_type_fields",
            "front_layout",
            "back_layout",
            "styling_tokens",
            "rendering_constraints",
        ],
        "next_step": "template_render_adapter",
    }

    output = (
        "Template workflow prepared. Blueprint is ready for rendering adapter: "
        f"template={template_id} v{template_version}, target={render_target}."
    )

    return {
        "template_blueprint": blueprint,
        "anki_payload": payload,
        "output": output,
        "status": "completed",
    }


def finalize_template_flow(state: CardTemplateState) -> Dict[str, Any]:
    """Finalize template workflow with stable output payload."""
    status = state.get("status") or "completed"
    output = state.get("output") or "Template workflow completed."
    if state.get("error"):
        status = "failed"
        output = state.get("output") or f"Template workflow failed: {state.get('error')}"
    blueprint = state.get("template_blueprint") or {}
    anki_payload = state.get("anki_payload") or {}
    return {
        "output": output,
        "status": status,
        "result": {
            "message": output,
            "status": status,
            "template_blueprint": blueprint,
            "anki_payload": anki_payload,
        }
    }
