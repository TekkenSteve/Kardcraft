from __future__ import annotations

import re
from typing import Any

from runtime_models import TemplateRenderInput

TOKEN_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
SECTION_PATTERN = re.compile(r"(?s){{\s*([#^])\s*([^{}]+?)\s*}}(.*?){{\s*/\s*([^{}]+?)\s*}}")
SOUND_PATTERN = re.compile(r"\[sound:([^\]]+)\]", flags=re.IGNORECASE)
IMG_PATTERN = re.compile(r"""<img[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>""", flags=re.IGNORECASE)
AUDIO_PATTERN = re.compile(r"""<audio[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>""", flags=re.IGNORECASE)
SOURCE_PATTERN = re.compile(r"""<source[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>""", flags=re.IGNORECASE)


def stable_id(seed: str) -> int:
    import hashlib

    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10], 16)


def normalize_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    if token[0] in {"#", "/", "^"}:
        token = token[1:].strip()
    if ":" in token:
        token = token.split(":")[-1].strip()
    return token


def normalize_fields(values: dict[str, Any] | None) -> dict[str, str]:
    if not values:
        return {}
    out: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        out[str(key)] = str(value)
    return out


def to_profile_name(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip().lower()


def extract_profiles(mapping_spec: dict[str, Any] | None) -> tuple[list[str], str]:
    mapping_spec = mapping_spec or {}
    profiles: list[str] = []

    declared = mapping_spec.get("profiles")
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict):
                name = to_profile_name(item.get("name"))
            else:
                name = to_profile_name(item)
            if name and name not in profiles:
                profiles.append(name)

    if not profiles:
        for key in ("profile", "template_profile", "card_type"):
            value = to_profile_name(mapping_spec.get(key))
            if value:
                profiles.append(value)
                break

    default_profile = to_profile_name(mapping_spec.get("default_profile"))
    if not default_profile and profiles:
        default_profile = profiles[0]
    if not default_profile:
        default_profile = "default"
    if default_profile not in profiles:
        profiles.append(default_profile)
    return profiles, default_profile


def profile_sample_fields(mapping_spec: dict[str, Any] | None, profile: str) -> dict[str, str]:
    mapping_spec = mapping_spec or {}
    out: dict[str, str] = {}

    global_samples = mapping_spec.get("sample_fields")
    if isinstance(global_samples, dict):
        out.update(normalize_fields(global_samples))

    profile_samples_map = mapping_spec.get("profile_samples")
    if isinstance(profile_samples_map, dict):
        profile_samples = profile_samples_map.get(profile)
        if isinstance(profile_samples, dict):
            out.update(normalize_fields(profile_samples))

    declared = mapping_spec.get("profiles")
    if isinstance(declared, list):
        for item in declared:
            if not isinstance(item, dict):
                continue
            if to_profile_name(item.get("name")) != profile:
                continue
            samples = item.get("sample_fields")
            if isinstance(samples, dict):
                out.update(normalize_fields(samples))
            break
    return out


def collect_fields(front_html: str, back_html: str) -> list[str]:
    fields: set[str] = set()
    for html in (front_html, back_html):
        for raw in TOKEN_PATTERN.findall(html):
            token = normalize_token(raw)
            if token and token != "FrontSide":
                fields.add(token)
    return sorted(fields)


def collect_section_fields(front_html: str, back_html: str) -> set[str]:
    fields: set[str] = set()
    for html in (front_html, back_html):
        for match in SECTION_PATTERN.finditer(html):
            name = normalize_token(match.group(2))
            if name:
                fields.add(name)
    return fields


def detect_profiles(
    front_html: str,
    back_html: str,
    mapping_spec: dict[str, Any] | None,
) -> tuple[list[str], dict[str, bool], str]:
    combined = (front_html + "\n" + back_html).lower()
    declared_profiles, declared_default = extract_profiles(mapping_spec)
    profiles: set[str] = set(declared_profiles)
    capabilities = {
        "supports_cloze": "{{cloze:" in combined,
        "supports_typing": "{{type:" in combined,
        "supports_conditional": "{{#" in combined or "{{^" in combined,
        "supports_frontside": "{{frontside}}" in combined,
        "supports_hint": "{{hint:" in combined,
        "supports_audio": "[sound:" in combined,
        "supports_latex": "[latex]" in combined or "[/latex]" in combined,
    }

    if not profiles:
        profiles.add(declared_default or "default")
    return sorted(profiles), capabilities, (declared_default or "default")


def choose_profile(req: TemplateRenderInput, available_profiles: list[str], default_profile: str) -> str:
    selected_profile = (req.template_profile or req.card_type or default_profile or "default").strip().lower()
    if selected_profile == "qa":
        selected_profile = "default"
    if selected_profile not in available_profiles:
        selected_profile = default_profile
    return selected_profile


def build_effective_fields(
    req: TemplateRenderInput,
    selected_profile: str,
    note_fields: list[str],
    section_fields: set[str],
) -> dict[str, str]:
    mapping_spec = req.mapping_spec or {}
    fields = profile_sample_fields(mapping_spec, selected_profile)
    fields.update(normalize_fields(req.sample_fields))

    for name in note_fields:
        if name in section_fields:
            continue
        fields.setdefault(name, f"{name} sample value")

    if not fields:
        fields = {
            "Front": "What is active recall?",
            "Back": "Actively retrieve information from memory.",
            "Text": "Active recall is better than passive review.",
            "Extra": "Used as fallback sample text.",
        }
    return fields


def compose_documents(
    front: str,
    back: str,
    css: str,
    req: TemplateRenderInput,
    selected_profile: str,
) -> tuple[str, str, list[str]]:
    warnings: list[str] = []

    runtime = ""
    if req.preview_mode == "safe":
        if req.js and req.js.strip():
            warnings.append("Template JS disabled in safe preview mode.")
    else:
        runtime = (
            f'<script>window.anki={{platform:"anki-runtime",templateProfile:"{selected_profile}"}};'
            'window.pycmd=function(){return null};</script>'
        )
        if req.js and req.js.strip():
            runtime += f"<script>{req.js}</script>"

    front_doc = (
        '<!doctype html><html><head><meta charset="utf-8" />'
        f"<style>{css}</style></head><body class=\"card\">{front}{runtime}</body></html>"
    )
    back_doc = (
        '<!doctype html><html><head><meta charset="utf-8" />'
        f"<style>{css}</style></head><body class=\"card\">{back}{runtime}</body></html>"
    )

    return front_doc, back_doc, warnings


def is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def sample_has_front_content(sample_by_ord: dict[str, str], rules: list[list[Any]]) -> bool:
    if not rules:
        return any(is_nonempty(v) for v in sample_by_ord.values())
    for rule in rules:
        if len(rule) < 3:
            continue
        mode = str(rule[1]).lower()
        indices = [int(v) for v in rule[2]] if isinstance(rule[2], list) else []
        values = [sample_by_ord.get(str(i), "") for i in indices]
        if mode == "all":
            return all(is_nonempty(v) for v in values)
        if mode == "any":
            return any(is_nonempty(v) for v in values)
    return True


def estimate_cloze_count(values: dict[str, str]) -> int:
    pattern = re.compile(r"{{c(\d+)::", flags=re.IGNORECASE)
    ids: set[str] = set()
    for v in values.values():
        for match in pattern.findall(v or ""):
            ids.add(match)
    return len(ids)


def extract_media_tags(*html_docs: str) -> list[str]:
    media: set[str] = set()
    for doc in html_docs:
        if not doc:
            continue
        for sound in SOUND_PATTERN.findall(doc):
            value = sound.strip()
            if value:
                media.add(f"sound:{value}")
        for src in IMG_PATTERN.findall(doc):
            value = src.strip()
            if value:
                media.add(f"img:{value}")
        for src in AUDIO_PATTERN.findall(doc):
            value = src.strip()
            if value:
                media.add(f"audio:{value}")
        for src in SOURCE_PATTERN.findall(doc):
            value = src.strip()
            if value:
                media.add(f"source:{value}")
    return sorted(media)
