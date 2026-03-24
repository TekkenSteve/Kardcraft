from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreviewRequest(BaseModel):
    template_id: str = ""
    version: int = 1
    front_html: str = ""
    back_html: str = ""
    css: str = ""
    js: str | None = None
    sample_fields: dict[str, Any] | None = None
    template_profile: str = ""
    card_type: str = ""
    preview_mode: str = "safe"
    mapping_spec: dict[str, Any] | None = None
    render_engine: str | None = None
    strict_validation: bool = False


class PackageCardRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class BuildApkgRequest(BaseModel):
    deck_name: str
    model_name: str
    field_names: list[str]
    qfmt: str
    afmt: str
    css: str = ""
    cards: list[PackageCardRequest] = Field(default_factory=list)
    package_name: str = "kardcraft_export"


class ValidateTemplateRequest(BaseModel):
    template_id: str = ""
    version: int = 1
    front_html: str
    back_html: str
    css: str = ""
    js: str | None = None
    sample_fields: dict[str, Any] | None = None
    mapping_spec: dict[str, Any] | None = None
    template_profile: str = ""
    card_type: str = ""


class RequiredFieldsRequest(BaseModel):
    front_html: str
    back_html: str
    css: str = ""


class PrecheckRequest(BaseModel):
    front_html: str
    back_html: str
    css: str = ""
    sample_fields: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = Field(default_factory=list)
