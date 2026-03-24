from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TemplateProfile = str
PreviewMode = Literal["safe", "high_fidelity"]


@dataclass(slots=True)
class TemplateRenderInput:
    template_id: str
    template_version: int
    front_html: str
    back_html: str
    css: str = ""
    js: str | None = None
    sample_fields: dict[str, Any] | None = None
    template_profile: TemplateProfile = ""
    card_type: str = ""  # backward compatibility alias
    preview_mode: PreviewMode = "safe"
    mapping_spec: dict[str, Any] | None = None


@dataclass(slots=True)
class TemplateRenderOutput:
    template_id: str
    template_version: int
    template_profile: TemplateProfile
    available_profiles: list[str]
    capabilities: dict[str, bool]
    card_type: str
    preview_mode: PreviewMode
    front_html_rendered: str
    back_html_rendered: str
    front_document: str
    back_document: str
    css: str
    media_tags: list[str]
    note_fields: list[str]
    warnings: list[str]


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None
    suggestion: str | None = None


@dataclass(slots=True)
class ValidationSummary:
    ok: bool
    errors: list[ValidationIssue]
    warnings: list[str]


@dataclass(slots=True)
class PackageCard:
    fields: dict[str, Any]
    tags: list[str]


@dataclass(slots=True)
class PackageBuildInput:
    deck_name: str
    model_name: str
    field_names: list[str]
    qfmt: str
    afmt: str
    css: str
    cards: list[PackageCard]
    package_name: str


@dataclass(slots=True)
class PackageBuildOutput:
    package_name: str
    file_name: str
    apkg_base64: str
    note_count: int
