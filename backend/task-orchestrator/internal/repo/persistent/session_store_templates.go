package persistent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func (s *SessionStore) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]TemplateCatalogRow, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	var total int
	if err := s.pg.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM kc_card_templates
		WHERE status = 'active'
		  AND (scope = 'system' OR owner_user_id = $1)
	`, userID).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
		SELECT
			t.template_id,
			t.name,
			COALESCE(t.description, ''),
			t.scope,
			COALESCE(t.owner_user_id, ''),
			t.status,
			t.is_default,
			t.latest_version,
			COALESCE(v.is_published, true) AS version_published,
			t.created_at,
			t.updated_at
		FROM kc_card_templates t
		LEFT JOIN kc_card_template_versions v
		  ON v.template_id = t.template_id AND v.version = t.latest_version
		WHERE t.status = 'active'
		  AND (t.scope = 'system' OR t.owner_user_id = $1)
		ORDER BY t.updated_at DESC, t.template_id ASC
		LIMIT $2 OFFSET $3
	`, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	out := make([]TemplateCatalogRow, 0, limit)
	for rows.Next() {
		var item TemplateCatalogRow
		if err := rows.Scan(
			&item.TemplateID,
			&item.Name,
			&item.Description,
			&item.Scope,
			&item.OwnerUserID,
			&item.Status,
			&item.IsDefault,
			&item.LatestVersion,
			&item.VersionPublished,
			&item.CreatedAt,
			&item.UpdatedAt,
		); err != nil {
			return nil, 0, err
		}
		out = append(out, item)
	}
	return out, total, rows.Err()
}

func (s *SessionStore) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*TemplateCatalogRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	var item TemplateCatalogRow
	var mappingRaw string
	err := s.pg.QueryRow(ctx, `
		SELECT
			t.template_id,
			t.name,
			COALESCE(t.description, ''),
			t.scope,
			COALESCE(t.owner_user_id, ''),
			t.status,
			t.is_default,
			t.latest_version,
			COALESCE(v.is_published, true) AS version_published,
			t.created_at,
			t.updated_at,
			COALESCE(v.front_html, ''),
			COALESCE(v.back_html, ''),
			COALESCE(v.css, ''),
			COALESCE(v.js, ''),
			COALESCE(v.mapping_spec::text, '{}')
		FROM kc_card_templates t
		LEFT JOIN kc_card_template_versions v
		  ON v.template_id = t.template_id AND v.version = t.latest_version
		WHERE t.template_id = $1
		  AND t.status = 'active'
		  AND (t.scope = 'system' OR t.owner_user_id = $2)
		LIMIT 1
	`, templateID, userID).Scan(
		&item.TemplateID,
		&item.Name,
		&item.Description,
		&item.Scope,
		&item.OwnerUserID,
		&item.Status,
		&item.IsDefault,
		&item.LatestVersion,
		&item.VersionPublished,
		&item.CreatedAt,
		&item.UpdatedAt,
		&item.FrontHTML,
		&item.BackHTML,
		&item.CSS,
		&item.JS,
		&mappingRaw,
	)
	if err != nil {
		return nil, err
	}
	item.MappingSpec = make(map[string]any)
	_ = json.Unmarshal([]byte(mappingRaw), &item.MappingSpec)
	return &item, nil
}

func (s *SessionStore) GetUserTemplatePreference(ctx context.Context, userID string) (*TemplateCatalogRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	item := &TemplateCatalogRow{}
	err := s.pg.QueryRow(ctx, `
		SELECT default_template_id, COALESCE(default_template_version, 1)
		FROM kc_user_template_preferences
		WHERE user_id = $1
	`, userID).Scan(&item.DefaultTemplateID, &item.DefaultTemplateVersion)
	if err != nil {
		return nil, err
	}
	return item, nil
}

func (s *SessionStore) GetResolvedDefaultTemplate(ctx context.Context, userID string) (*TemplateCatalogRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}

	// 1) Legacy-compatible explicit user preference takes highest priority.
	pref := &TemplateCatalogRow{}
	err := s.pg.QueryRow(ctx, `
		SELECT pref.default_template_id, pref.default_template_version
		FROM kc_user_template_preferences pref
		JOIN kc_card_templates t
		  ON t.template_id = pref.default_template_id
		 AND t.status = 'active'
		 AND (t.scope = 'system' OR t.owner_user_id = $1)
		JOIN kc_card_template_versions v
		  ON v.template_id = pref.default_template_id
		 AND v.version = pref.default_template_version
		WHERE pref.user_id = $1
		LIMIT 1
	`, userID).Scan(&pref.DefaultTemplateID, &pref.DefaultTemplateVersion)
	if err == nil {
		return pref, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}

	// 2) Policy-based resolution fallback: user scope then system scope.
	policy := &TemplateCatalogRow{}
	err = s.pg.QueryRow(ctx, `
		SELECT p.default_template_id, p.default_template_version
		FROM kc_template_default_policies p
		JOIN kc_card_templates t
		  ON t.template_id = p.default_template_id
		 AND t.status = 'active'
		 AND (t.scope = 'system' OR t.owner_user_id = $1)
		JOIN kc_card_template_versions v
		  ON v.template_id = p.default_template_id
		 AND v.version = p.default_template_version
		WHERE
			(p.scope_type = 'user' AND p.scope_id = $1)
			OR p.scope_type = 'system'
		ORDER BY
			CASE WHEN p.scope_type = 'user' THEN 0 ELSE 1 END,
			p.updated_at DESC,
			p.default_template_id ASC
		LIMIT 1
	`, userID).Scan(&policy.DefaultTemplateID, &policy.DefaultTemplateVersion)
	if err == nil {
		return policy, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, pgx.ErrNoRows
	}
	var pgErr *pgconn.PgError
	// Table may not exist before migration cutover; treat as no-default.
	if errors.As(err, &pgErr) && pgErr.Code == "42P01" {
		return nil, pgx.ErrNoRows
	}
	return nil, err
}

func (s *SessionStore) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	if version <= 0 {
		version = 1
	}
	_, err := s.pg.Exec(ctx, `
		INSERT INTO kc_user_template_preferences (user_id, default_template_id, default_template_version, updated_at)
		VALUES ($1, $2, $3, NOW())
		ON CONFLICT (user_id) DO UPDATE
		SET default_template_id = EXCLUDED.default_template_id,
		    default_template_version = EXCLUDED.default_template_version,
		    updated_at = NOW()
	`, userID, templateID, version)
	return err
}
