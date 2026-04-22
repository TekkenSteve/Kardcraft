-- Enforce that at most one template can be marked as default.

SET search_path TO public;

-- Normalize historical data before creating the unique partial index.
WITH ranked_defaults AS (
    SELECT
        template_id,
        ROW_NUMBER() OVER (
            ORDER BY
                (template_id = 'anki-quizify') DESC,
                updated_at DESC,
                created_at DESC,
                template_id ASC
        ) AS rn
    FROM kc_card_templates
    WHERE is_default = TRUE
)
UPDATE kc_card_templates t
SET
    is_default = FALSE,
    updated_at = NOW()
FROM ranked_defaults d
WHERE t.template_id = d.template_id
  AND d.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_kc_card_templates_single_default
    ON kc_card_templates (is_default)
    WHERE is_default = TRUE;
