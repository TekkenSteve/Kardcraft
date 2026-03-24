from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException

from engines import NativeAnkiEngine, PackageBuilder
from infra import PreviewLRUCache
from runtime_models import (
    PackageBuildInput,
    PackageCard,
    TemplateRenderInput,
    ValidationIssue,
    ValidationSummary,
)
from schemas import (
    BuildApkgRequest,
    PrecheckRequest,
    PreviewRequest,
    RequiredFieldsRequest,
    ValidateTemplateRequest,
)
from template_utils import (
    estimate_cloze_count,
    normalize_fields,
    sample_has_front_content,
)

app = FastAPI(title="kardcraft-anki-runtime", version="1.1.0")

native_engine = NativeAnkiEngine()
package_builder = PackageBuilder()
preview_cache = PreviewLRUCache(max_size=int(os.getenv("ANKI_PREVIEW_CACHE_SIZE", "256")))
DEFAULT_PREVIEW_ENGINE = "native_anki"
DEFAULT_STRICT_VALIDATION = os.getenv("ANKI_PREVIEW_STRICT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}


def _to_issue(code: str, message: str, field: str | None = None, suggestion: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, field=field, suggestion=suggestion)


def _native_error_to_issue(exc: Exception) -> ValidationIssue:
    message = str(exc).strip() or exc.__class__.__name__
    lower = message.lower()

    if "no field named" in lower or "field named" in lower:
        return _to_issue(
            code="MISSING_FIELD",
            message=message,
            suggestion="Add the missing field in template fields or fix token names in qfmt/afmt.",
        )
    if "expected" in lower or "parse" in lower or "syntax" in lower:
        return _to_issue(
            code="TEMPLATE_SYNTAX_ERROR",
            message=message,
            suggestion="Check mustache sections/tags and ensure delimiters are balanced.",
        )
    if "cloze" in lower:
        return _to_issue(
            code="CLOZE_TEMPLATE_ERROR",
            message=message,
            suggestion="Ensure cloze placeholders and cloze note type are consistent.",
        )
    return _to_issue(
        code="TEMPLATE_RENDER_ERROR",
        message=message,
        suggestion="Fix the template according to the render error and retry validation.",
    )


def _preview_response(
    output: Any,
    validation: ValidationSummary,
    engine_used: str,
    engine_fallback: bool = False,
) -> dict[str, Any]:
    payload = asdict(output)
    payload["engine_used"] = engine_used
    payload["engine_fallback"] = engine_fallback
    payload["validation"] = asdict(validation)
    return payload


def _preview_cache_key(req: PreviewRequest) -> str:
    payload = {
        "template_id": req.template_id,
        "version": req.version,
        "front_html": req.front_html,
        "back_html": req.back_html,
        "css": req.css,
        "js": req.js,
        "sample_fields": req.sample_fields or {},
        "template_profile": req.template_profile,
        "card_type": req.card_type,
        "preview_mode": req.preview_mode,
        "mapping_spec": req.mapping_spec or {},
        "render_engine": req.render_engine or DEFAULT_PREVIEW_ENGINE,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.get("/health")
async def health() -> dict[str, Any]:
    pool_stats = native_engine.pool_stats()
    return {
        "status": "ok",
        "preview_engine_default": DEFAULT_PREVIEW_ENGINE,
        "native_anki_available": native_engine.available,
        "preview_strict_default": DEFAULT_STRICT_VALIDATION,
        "collection_pool": pool_stats,
        "preview_cache": preview_cache.stats(),
    }


@app.get("/version")
async def version() -> dict[str, Any]:
    anki_version = "unknown"
    try:
        from importlib.metadata import version as pkg_version

        anki_version = pkg_version("anki")
    except Exception:
        pass
    return {
        "service_version": app.version,
        "anki_version": anki_version,
        "preview_engine_default": DEFAULT_PREVIEW_ENGINE,
    }


@app.post("/internal/anki/preview")
async def preview(req: PreviewRequest) -> dict[str, Any]:
    if not req.front_html.strip() or not req.back_html.strip():
        raise HTTPException(status_code=400, detail="front_html and back_html are required")

    selected_engine = (req.render_engine or DEFAULT_PREVIEW_ENGINE).strip().lower()
    if selected_engine in {"simple", "legacy"}:
        raise HTTPException(
            status_code=400,
            detail="render_engine=simple is disabled; use native_anki only",
        )
    strict_validation = req.strict_validation or DEFAULT_STRICT_VALIDATION
    cache_key = _preview_cache_key(req)
    cached = preview_cache.get(cache_key)
    if cached is not None:
        return cached

    render_input = TemplateRenderInput(
        template_id=req.template_id,
        template_version=req.version,
        front_html=req.front_html,
        back_html=req.back_html,
        css=req.css,
        js=req.js,
        sample_fields=req.sample_fields or {},
        template_profile=req.template_profile,
        card_type=req.card_type,
        preview_mode="high_fidelity" if req.preview_mode == "high_fidelity" else "safe",
        mapping_spec=req.mapping_spec or {},
    )

    try:
        if not native_engine.available:
            raise HTTPException(
                status_code=503,
                detail=f"native anki engine unavailable: {native_engine.import_error}",
            )

        output = native_engine.render_preview(render_input)
        validation = ValidationSummary(
            ok=True,
            errors=[],
            warnings=list(output.warnings),
        )
        payload = _preview_response(output, validation, engine_used="native_anki", engine_fallback=False)
        preview_cache.set(cache_key, payload)
        return payload
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        issue = _native_error_to_issue(exc)
        detail = {
            "engine_used": "native_anki",
            "engine_fallback": False,
            "validation": asdict(
                ValidationSummary(
                    ok=False,
                    errors=[issue],
                    warnings=[],
                )
            ),
        }
        if strict_validation:
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(status_code=422, detail=detail) from exc


@app.post("/internal/anki/validate-template")
async def validate_template(req: ValidateTemplateRequest) -> dict[str, Any]:
    payload = await preview(
        PreviewRequest(
            template_id=req.template_id,
            version=req.version,
            front_html=req.front_html,
            back_html=req.back_html,
            css=req.css,
            js=req.js,
            sample_fields=req.sample_fields or {},
            template_profile=req.template_profile,
            card_type=req.card_type,
            preview_mode="safe",
            mapping_spec=req.mapping_spec or {},
            strict_validation=True,
        )
    )
    return {
        "valid": True,
        "validation": payload.get("validation"),
        "note_fields": payload.get("note_fields", []),
        "available_profiles": payload.get("available_profiles", []),
        "capabilities": payload.get("capabilities", {}),
    }


@app.post("/internal/anki/required-fields")
async def required_fields(req: RequiredFieldsRequest) -> dict[str, Any]:
    try:
        field_names, req_rules, _ = native_engine.compute_required_fields(
            front_html=req.front_html,
            back_html=req.back_html,
            css=req.css,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    card_templates: list[dict[str, Any]] = []
    required_fields_per_card: dict[str, list[str]] = {}

    for rule in req_rules:
        if len(rule) < 3:
            continue
        template_ord = int(rule[0])
        mode = str(rule[1])
        ords = [int(v) for v in rule[2]] if isinstance(rule[2], list) else []
        names = [field_names[i] for i in ords if 0 <= i < len(field_names)]
        card_key = f"card_{template_ord + 1}"
        required_fields_per_card[card_key] = names
        card_templates.append(
            {
                "template_ord": template_ord,
                "mode": mode,
                "required_field_ords": ords,
                "required_field_names": names,
            }
        )

    return {
        "field_names": field_names,
        "card_templates": card_templates,
        "required_fields_per_card": required_fields_per_card,
    }


@app.post("/internal/anki/precheck")
async def precheck(req: PrecheckRequest) -> dict[str, Any]:
    try:
        field_names, req_rules, is_cloze = native_engine.compute_required_fields(
            front_html=req.front_html,
            back_html=req.back_html,
            css=req.css,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    samples = list(req.samples or [])
    if not samples:
        samples = [req.sample_fields or {}]

    empty_cards: list[int] = []
    card_count = 0

    for idx, raw in enumerate(samples):
        normalized = normalize_fields(raw)
        sample_by_ord = {str(i): normalized.get(name, "") for i, name in enumerate(field_names)}
        has_front = sample_has_front_content(sample_by_ord, req_rules)
        if not has_front:
            empty_cards.append(idx)
            continue
        if is_cloze:
            cloze_cards = estimate_cloze_count(normalized)
            if cloze_cards <= 0:
                empty_cards.append(idx)
                continue
            card_count += cloze_cards
        else:
            card_count += 1

    return {
        "would_generate_empty": len(empty_cards) > 0,
        "card_count": card_count,
        "empty_cards": empty_cards,
        "is_multi_card": card_count > 1,
    }


@app.post("/internal/anki/build-apkg")
async def build_apkg(req: BuildApkgRequest) -> dict[str, Any]:
    try:
        output = package_builder.build_apkg(
            PackageBuildInput(
                deck_name=req.deck_name,
                model_name=req.model_name,
                field_names=req.field_names,
                qfmt=req.qfmt,
                afmt=req.afmt,
                css=req.css,
                cards=[PackageCard(fields=c.fields, tags=c.tags) for c in req.cards],
                package_name=req.package_name,
            )
        )
        return asdict(output)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.on_event("shutdown")
async def shutdown_event() -> None:
    native_engine.shutdown()
