"""Business service for template selection in main_graph."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from kardcraft.db import CardTemplateRepository

ANKI_RUNTIME_URL = os.getenv("ANKI_RUNTIME_URL", "http://anki-runtime:8012").rstrip("/")
TOKEN_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


class TemplatePreparationError(Exception):
    def __init__(self, message: str, validation: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.validation = validation


@dataclass
class PreparedTemplateContext:
    template_id: str
    template_name: str
    template_version: int
    template_profiles: list[str]
    template_default_profile: str
    selected_template_profile: str
    template_note_fields: list[str]
    template_validation: dict[str, Any]


def _normalize_profile_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _extract_profiles_from_mapping(mapping_spec: dict[str, Any] | None) -> tuple[list[str], str]:
    mapping = mapping_spec or {}
    profiles: list[str] = []
    declared = mapping.get("profiles")
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict):
                name = _normalize_profile_name(item.get("name"))
            else:
                name = _normalize_profile_name(item)
            if name and name not in profiles:
                profiles.append(name)

    default_profile = _normalize_profile_name(mapping.get("default_profile"))
    if not default_profile and profiles:
        default_profile = profiles[0]
    if not default_profile:
        default_profile = "default"
    if default_profile not in profiles:
        profiles.append(default_profile)

    return profiles, default_profile


def _extract_note_fields(front_html: str, back_html: str) -> list[str]:
    fields: set[str] = set()
    for html in (front_html, back_html):
        for raw in TOKEN_PATTERN.findall(html or ""):
            token = raw.strip()
            if not token:
                continue
            if token[0] in {"#", "/", "^"}:
                token = token[1:].strip()
            if ":" in token:
                token = token.split(":")[-1].strip()
            if token and token != "FrontSide":
                fields.add(token)
    return sorted(fields)


def _build_validation_payload(
    *,
    template_id: str,
    template_version: int,
    topic: str,
    front_html: str,
    back_html: str,
    css: str,
    js: Any,
    mapping_spec: dict[str, Any],
    selected_profile: str,
) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "version": template_version,
        "front_html": front_html,
        "back_html": back_html,
        "css": css,
        "js": js,
        "sample_fields": {
            "Front": topic or "Template validation sample",
            "Back": "Template validation sample back",
        },
        "mapping_spec": mapping_spec,
        "template_profile": selected_profile,
        "strict_validation": True,
    }


async def _validate_template_with_runtime(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    validation_summary: dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
    note_fields: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{ANKI_RUNTIME_URL}/internal/anki/preview", json=payload)
    except Exception as exc:
        validation_summary = {
            "ok": False,
            "errors": [{"code": "TEMPLATE_VALIDATION_UNAVAILABLE", "message": str(exc)}],
            "warnings": [],
        }
        raise TemplatePreparationError(
            f"template validation service unavailable for template: {payload.get('template_id')}",
            validation=validation_summary,
        ) from exc

    if resp.status_code >= 400:
        detail: dict[str, Any]
        try:
            parsed = resp.json().get("detail", {})
            detail = parsed if isinstance(parsed, dict) else {"message": str(parsed)}
        except Exception:
            detail = {"message": resp.text}

        validation = detail.get("validation") if isinstance(detail, dict) else None
        if isinstance(validation, dict):
            validation_summary = validation
        else:
            validation_summary = {
                "ok": False,
                "errors": [{"code": "TEMPLATE_PREVIEW_FAILED", "message": str(detail)}],
                "warnings": [],
            }
        raise TemplatePreparationError(
            f"selected template validation failed: {payload.get('template_id')}",
            validation=validation_summary,
        )

    preview_result = resp.json()
    validation_summary = preview_result.get("validation") or validation_summary
    preview_note_fields = preview_result.get("note_fields")
    if isinstance(preview_note_fields, list):
        note_fields = [str(item) for item in preview_note_fields if isinstance(item, str)]

    return validation_summary, note_fields


async def prepare_template_context_for_main_graph(
    *,
    user_id: str,
    topic: str,
    state_template_id: Any,
    state_template_version: Any,
    state_selected_profile: Any,
    context_payload: dict[str, Any] | None,
    repository: CardTemplateRepository | None = None,
) -> PreparedTemplateContext:
    context = context_payload if isinstance(context_payload, dict) else {}

    template_id = str(state_template_id or context.get("template_id") or "").strip()
    if not template_id:
        raise TemplatePreparationError(
            "template_id is required: select a card template before starting content card generation."
        )

    selected_profile = str(
        state_selected_profile
        or context.get("template_profile")
        or ""
    ).strip() or None

    template_version_raw = state_template_version or context.get("template_version")
    try:
        template_version = int(template_version_raw or 0)
    except Exception:
        template_version = 0

    repo = repository or CardTemplateRepository()
    try:
        template = await repo.get_accessible_active_template(
            template_id=template_id,
            user_id=user_id,
            version=template_version,
        )
    except Exception as exc:
        raise TemplatePreparationError(f"failed to load selected template: {exc}") from exc

    if template is None:
        raise TemplatePreparationError(
            f"selected template not found or inaccessible: {template_id}"
        )

    if not template.front_html.strip() or not template.back_html.strip():
        raise TemplatePreparationError(f"selected template is incomplete: {template_id}")

    template_profiles, default_profile = _extract_profiles_from_mapping(template.mapping_spec)

    if selected_profile and selected_profile not in template_profiles:
        selected_profile = default_profile
    if not selected_profile:
        selected_profile = default_profile

    note_fields = _extract_note_fields(template.front_html, template.back_html)
    validation_payload = _build_validation_payload(
        template_id=template.template_id,
        template_version=template.version,
        topic=topic,
        front_html=template.front_html,
        back_html=template.back_html,
        css=template.css,
        js=template.js,
        mapping_spec=template.mapping_spec,
        selected_profile=selected_profile,
    )

    validation_summary, runtime_note_fields = await _validate_template_with_runtime(validation_payload)
    if not note_fields:
        note_fields = runtime_note_fields

    return PreparedTemplateContext(
        template_id=template.template_id,
        template_name=template.name,
        template_version=template.version,
        template_profiles=template_profiles,
        template_default_profile=default_profile,
        selected_template_profile=selected_profile,
        template_note_fields=note_fields,
        template_validation=validation_summary,
    )
