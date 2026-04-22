-- Enforce referential integrity for default template version preferences.
-- A preference must point to an existing (template_id, version) row.

SET search_path TO public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_kc_user_template_preferences_template_version'
    ) THEN
        -- Remove stale preferences that reference missing template versions.
        DELETE FROM kc_user_template_preferences pref
        WHERE NOT EXISTS (
            SELECT 1
            FROM kc_card_template_versions ver
            WHERE ver.template_id = pref.default_template_id
              AND ver.version = pref.default_template_version
        );

        ALTER TABLE kc_user_template_preferences
            ADD CONSTRAINT fk_kc_user_template_preferences_template_version
            FOREIGN KEY (default_template_id, default_template_version)
            REFERENCES kc_card_template_versions (template_id, version)
            ON DELETE RESTRICT;
    END IF;
END $$;
