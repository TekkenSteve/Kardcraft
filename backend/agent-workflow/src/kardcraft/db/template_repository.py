"""Repository for card-template persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from .postgres import postgres


@dataclass
class CardTemplateVersionBundle:
    template_id: str
    name: str
    version: int
    front_html: str
    back_html: str
    css: str
    js: Any
    mapping_spec: dict[str, Any]
    source: str = "postgres"


class CardTemplateRepository:
    """DAO layer for reading active template versions from PostgreSQL."""

    async def get_accessible_active_template(
        self,
        *,
        template_id: str,
        user_id: str,
        version: int = 0,
    ) -> CardTemplateVersionBundle | None:
        query = text(
            """
            SELECT
                t.template_id,
                t.name,
                COALESCE(v.version, t.latest_version) AS version,
                v.front_html,
                v.back_html,
                v.css,
                v.js,
                v.mapping_spec,
                COALESCE((t.metadata->>'source'), 'postgres') AS source
            FROM kc_card_templates t
            JOIN kc_card_template_versions v
              ON v.template_id = t.template_id
             AND v.version = CASE
                 WHEN :version > 0 THEN :version
                 ELSE t.latest_version
             END
            WHERE t.template_id = :template_id
              AND t.status = 'active'
              AND (
                   t.scope = 'system'
                OR t.owner_user_id = :user_id
              )
            LIMIT 1
            """
        )

        async with postgres.session() as session:
            row = await session.execute(
                query,
                {
                    "template_id": template_id,
                    "version": version,
                    "user_id": user_id,
                },
            )
            record = row.mappings().first()

        if record is None:
            return None

        mapping_spec = record["mapping_spec"]
        if not isinstance(mapping_spec, dict):
            mapping_spec = {}

        return CardTemplateVersionBundle(
            template_id=str(record["template_id"]),
            name=str(record["name"] or ""),
            version=int(record["version"] or 1),
            front_html=str(record["front_html"] or ""),
            back_html=str(record["back_html"] or ""),
            css=str(record["css"] or ""),
            js=record["js"],
            mapping_spec=mapping_spec,
            source=str(record["source"] or "postgres"),
        )

