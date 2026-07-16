package persistent

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"task-orchestrator/internal/repo"
)

// APKGExportStore persists Kardcraft's export business state independently of
// workspace projections and River's queue records.
type APKGExportStore struct {
	store *SessionStore
}

func NewAPKGExportStore(store *SessionStore) *APKGExportStore {
	return &APKGExportStore{store: store}
}

func (s *APKGExportStore) CreateAPKGExport(ctx context.Context, export repo.APKGExport) error {
	if s == nil || s.store == nil || s.store.pg == nil {
		return fmt.Errorf("APKG export store postgres unavailable")
	}
	export = normalizeAPKGExport(export)
	if export.ExportID == "" || export.SessionID == "" || export.UserID == "" || export.Status != "queued" {
		return fmt.Errorf("APKG export requires id, session, user, and queued status")
	}
	_, err := s.store.pg.Exec(ctx, `
		INSERT INTO kc_apkg_exports (export_id, session_id, user_id, template_id, deck_name, package_name, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, export.ExportID, export.SessionID, export.UserID, export.TemplateID, export.DeckName, export.PackageName, export.Status)
	if err != nil {
		return fmt.Errorf("create APKG export: %w", err)
	}
	return nil
}

func (s *APKGExportStore) GetAPKGExport(ctx context.Context, exportID, sessionID, userID string) (repo.APKGExport, bool, error) {
	if s == nil || s.store == nil || s.store.pg == nil {
		return repo.APKGExport{}, false, fmt.Errorf("APKG export store postgres unavailable")
	}
	var export repo.APKGExport
	var completedAt *time.Time
	err := s.store.pg.QueryRow(ctx, `
		SELECT export_id, session_id, user_id, template_id, deck_name, package_name, status, confirmed_count,
		       file_name, file_size, apkg_bytes, error_message, created_at, updated_at, completed_at
		FROM kc_apkg_exports
		WHERE export_id = $1 AND session_id = $2 AND user_id = $3
	`, strings.TrimSpace(exportID), strings.TrimSpace(sessionID), strings.TrimSpace(userID)).Scan(
		&export.ExportID, &export.SessionID, &export.UserID, &export.TemplateID, &export.DeckName, &export.PackageName,
		&export.Status, &export.ConfirmedCount, &export.FileName, &export.FileSize, &export.APKGBytes, &export.ErrorMessage,
		&export.CreatedAt, &export.UpdatedAt, &completedAt,
	)
	if err == pgx.ErrNoRows {
		return repo.APKGExport{}, false, nil
	}
	if err != nil {
		return repo.APKGExport{}, false, fmt.Errorf("get APKG export: %w", err)
	}
	export.CompletedAt = completedAt
	return export, true, nil
}

func (s *APKGExportStore) GetAPKGExportByID(ctx context.Context, exportID string) (repo.APKGExport, bool, error) {
	if s == nil || s.store == nil || s.store.pg == nil {
		return repo.APKGExport{}, false, fmt.Errorf("APKG export store postgres unavailable")
	}
	var export repo.APKGExport
	var completedAt *time.Time
	err := s.store.pg.QueryRow(ctx, `
		SELECT export_id, session_id, user_id, template_id, deck_name, package_name, status, confirmed_count,
		       file_name, file_size, apkg_bytes, error_message, created_at, updated_at, completed_at
		FROM kc_apkg_exports
		WHERE export_id = $1
	`, strings.TrimSpace(exportID)).Scan(
		&export.ExportID, &export.SessionID, &export.UserID, &export.TemplateID, &export.DeckName, &export.PackageName,
		&export.Status, &export.ConfirmedCount, &export.FileName, &export.FileSize, &export.APKGBytes, &export.ErrorMessage,
		&export.CreatedAt, &export.UpdatedAt, &completedAt,
	)
	if err == pgx.ErrNoRows {
		return repo.APKGExport{}, false, nil
	}
	if err != nil {
		return repo.APKGExport{}, false, fmt.Errorf("get APKG export by id: %w", err)
	}
	export.CompletedAt = completedAt
	return export, true, nil
}

func (s *APKGExportStore) MarkAPKGExportRunning(ctx context.Context, exportID string) error {
	return s.updateStatus(ctx, exportID, "running", "")
}

// RetryAPKGExport returns the business record to its queued state while River
// schedules the next delivery. A final failure is recorded only once River has
// exhausted the job's retry budget.
func (s *APKGExportStore) RetryAPKGExport(ctx context.Context, exportID, reason string) error {
	return s.updateStatus(ctx, exportID, "queued", reason)
}

func (s *APKGExportStore) CompleteAPKGExport(ctx context.Context, export repo.APKGExport) error {
	if s == nil || s.store == nil || s.store.pg == nil {
		return fmt.Errorf("APKG export store postgres unavailable")
	}
	export = normalizeAPKGExport(export)
	if export.ExportID == "" || export.FileName == "" || len(export.APKGBytes) == 0 {
		return fmt.Errorf("completed APKG export requires id, file name, and payload")
	}
	_, err := s.store.pg.Exec(ctx, `
		UPDATE kc_apkg_exports
		SET template_id = $2, deck_name = $3, package_name = $4, status = 'completed', confirmed_count = $5,
		    file_name = $6, file_size = $7, apkg_bytes = $8, error_message = '', completed_at = NOW(), updated_at = NOW()
		WHERE export_id = $1
	`, export.ExportID, export.TemplateID, export.DeckName, export.PackageName, export.ConfirmedCount,
		export.FileName, export.FileSize, export.APKGBytes)
	if err != nil {
		return fmt.Errorf("complete APKG export: %w", err)
	}
	return nil
}

func (s *APKGExportStore) FailAPKGExport(ctx context.Context, exportID, reason string) error {
	return s.updateStatus(ctx, exportID, "failed", reason)
}

func (s *APKGExportStore) updateStatus(ctx context.Context, exportID, status, reason string) error {
	if s == nil || s.store == nil || s.store.pg == nil {
		return fmt.Errorf("APKG export store postgres unavailable")
	}
	_, err := s.store.pg.Exec(ctx, `
		UPDATE kc_apkg_exports SET status = $2, error_message = $3, updated_at = NOW() WHERE export_id = $1
	`, strings.TrimSpace(exportID), status, strings.TrimSpace(reason))
	if err != nil {
		return fmt.Errorf("update APKG export status: %w", err)
	}
	return nil
}

func normalizeAPKGExport(export repo.APKGExport) repo.APKGExport {
	export.ExportID = strings.TrimSpace(export.ExportID)
	export.SessionID = strings.TrimSpace(export.SessionID)
	export.UserID = strings.TrimSpace(export.UserID)
	export.TemplateID = strings.TrimSpace(export.TemplateID)
	export.DeckName = strings.TrimSpace(export.DeckName)
	export.PackageName = strings.TrimSpace(export.PackageName)
	export.Status = strings.TrimSpace(export.Status)
	export.FileName = strings.TrimSpace(export.FileName)
	export.ErrorMessage = strings.TrimSpace(export.ErrorMessage)
	return export
}
