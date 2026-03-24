from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any

from infra import CollectionPool
from runtime_models import (
    PackageBuildInput,
    PackageBuildOutput,
    TemplateRenderInput,
    TemplateRenderOutput,
)
from template_utils import (
    build_effective_fields,
    choose_profile,
    collect_fields,
    collect_section_fields,
    compose_documents,
    detect_profiles,
    extract_media_tags,
    normalize_fields,
    stable_id,
)


class NativeAnkiEngine:
    """Official Anki core based renderer/validator."""

    def __init__(self) -> None:
        self.available = False
        self._import_error = ""
        self._Collection = None
        self._TemplateRenderContext = None
        self._MODEL_CLOZE = None
        self._pool: CollectionPool | None = None

        try:
            from anki.collection import Collection
            from anki.consts import MODEL_CLOZE
            from anki.template import TemplateRenderContext

            self._Collection = Collection
            self._MODEL_CLOZE = MODEL_CLOZE
            self._TemplateRenderContext = TemplateRenderContext
            pool_size = int(os.getenv("ANKI_COLLECTION_POOL_SIZE", "4"))
            self._pool = CollectionPool(Collection, max_size=pool_size)
            self.available = True
        except Exception as exc:  # pragma: no cover
            self._import_error = str(exc)

    @property
    def import_error(self) -> str:
        return self._import_error

    def pool_stats(self) -> dict[str, int] | None:
        if self._pool is None:
            return None
        return self._pool.stats()

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown()

    def render_preview(self, req: TemplateRenderInput) -> TemplateRenderOutput:
        if not self.available:
            raise RuntimeError(f"native anki engine unavailable: {self._import_error}")

        note_fields = collect_fields(req.front_html, req.back_html)
        section_fields = collect_section_fields(req.front_html, req.back_html)
        available_profiles, capabilities, default_profile = detect_profiles(
            req.front_html, req.back_html, req.mapping_spec
        )
        selected_profile = choose_profile(req, available_profiles, default_profile)
        fields = build_effective_fields(req, selected_profile, note_fields, section_fields)

        ordered_fields = list(note_fields)
        for key in fields.keys():
            if key not in ordered_fields:
                ordered_fields.append(key)
        if not ordered_fields:
            ordered_fields = ["Front", "Back", "Text", "Extra"]

        TemplateRenderContext = self._TemplateRenderContext
        MODEL_CLOZE = self._MODEL_CLOZE

        assert TemplateRenderContext is not None

        if self._pool is None:
            raise RuntimeError("native anki collection pool unavailable")
        handle = self._pool.acquire()
        col = handle.col
        try:
            mm = col.models
            model = mm.new(f"Kardcraft Preview::{req.template_id or 'adhoc'}::{req.template_version}")
            for name in ordered_fields:
                mm.add_field(model, mm.new_field(name))

            template = mm.new_template("Card 1")
            template["qfmt"] = req.front_html
            template["afmt"] = req.back_html
            mm.add_template(model, template)
            model["css"] = req.css
            if "{{cloze:" in (req.front_html + req.back_html).lower():
                model["type"] = MODEL_CLOZE
            mm.add(model)

            note = col.new_note(model)
            for idx, name in enumerate(ordered_fields):
                note.fields[idx] = fields.get(name, "")

            card = note.ephemeral_card()
            ctx = TemplateRenderContext.from_card_layout(
                note=note,
                card=card,
                notetype=note.note_type(),
                template=template,
                fill_empty=False,
            )
            rendered = ctx.render()
            front = rendered.question_text
            back = rendered.answer_text
            css = rendered.css or req.css
        finally:
            self._pool.release(handle)

        front_doc, back_doc, warnings = compose_documents(front, back, css, req, selected_profile)
        media_tags = extract_media_tags(front, back, front_doc, back_doc)

        return TemplateRenderOutput(
            template_id=req.template_id,
            template_version=req.template_version,
            template_profile=selected_profile,
            available_profiles=available_profiles,
            capabilities=capabilities,
            card_type=selected_profile,
            preview_mode=req.preview_mode,
            front_html_rendered=front,
            back_html_rendered=back,
            front_document=front_doc,
            back_document=back_doc,
            css=css,
            media_tags=media_tags,
            note_fields=ordered_fields,
            warnings=warnings,
        )

    def compute_required_fields(
        self,
        *,
        front_html: str,
        back_html: str,
        css: str = "",
    ) -> tuple[list[str], list[list[Any]], bool]:
        if not self.available:
            raise RuntimeError(f"native anki engine unavailable: {self._import_error}")

        note_fields = collect_fields(front_html, back_html)
        ordered_fields = list(note_fields) if note_fields else ["Front", "Back"]
        is_cloze = "{{cloze:" in (front_html + back_html).lower()

        MODEL_CLOZE = self._MODEL_CLOZE
        if self._pool is None:
            raise RuntimeError("native anki collection pool unavailable")
        handle = self._pool.acquire()
        col = handle.col
        try:
            mm = col.models
            model = mm.new("Kardcraft Required Fields")
            for name in ordered_fields:
                mm.add_field(model, mm.new_field(name))
            template = mm.new_template("Card 1")
            template["qfmt"] = front_html
            template["afmt"] = back_html
            mm.add_template(model, template)
            model["css"] = css
            if is_cloze:
                model["type"] = MODEL_CLOZE
            mm.add(model)
            req_rules = model.get("req") or []
        finally:
            self._pool.release(handle)

        return ordered_fields, req_rules, is_cloze


class PackageBuilder:
    def build_apkg(self, req: PackageBuildInput) -> PackageBuildOutput:
        import genanki

        if not req.cards:
            raise ValueError("cards is required")

        model_id = stable_id(f"model:{req.model_name}:{','.join(req.field_names)}")
        deck_id = stable_id(f"deck:{req.deck_name}")

        model = genanki.Model(
            model_id=model_id,
            name=req.model_name,
            fields=[{"name": field} for field in req.field_names],
            templates=[{"name": "Card 1", "qfmt": req.qfmt, "afmt": req.afmt}],
            css=req.css,
        )
        deck = genanki.Deck(deck_id=deck_id, name=req.deck_name)

        for card in req.cards:
            normalized = normalize_fields(card.fields)
            ordered = [normalized.get(name, "") for name in req.field_names]
            note = genanki.Note(model=model, fields=ordered, tags=card.tags)
            deck.add_note(note)

        with tempfile.TemporaryDirectory(prefix="anki_runtime_apkg_") as tmpdir:
            out_path = Path(tmpdir) / f"{req.package_name}.apkg"
            genanki.Package(deck).write_to_file(str(out_path))
            raw = out_path.read_bytes()

        return PackageBuildOutput(
            package_name=req.package_name,
            file_name=f"{req.package_name}.apkg",
            apkg_base64=base64.b64encode(raw).decode("ascii"),
            note_count=len(req.cards),
        )
