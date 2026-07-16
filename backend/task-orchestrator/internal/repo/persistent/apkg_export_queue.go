package persistent

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/riverqueue/river"
	"github.com/riverqueue/river/riverdriver/riverpgxv5"

	"task-orchestrator/internal/repo"
)

const APKGExportQueue = "exports"

// CreateAndEnqueueAPKGExport atomically persists a business export request
// and its River job. River owns retries; Kardcraft owns the export state.
func (s *APKGExportStore) CreateAndEnqueueAPKGExport(ctx context.Context, export repo.APKGExport) error {
	if s == nil || s.store == nil || s.store.pg == nil {
		return fmt.Errorf("APKG export store postgres unavailable")
	}
	export = normalizeAPKGExport(export)
	if export.ExportID == "" || export.SessionID == "" || export.UserID == "" || export.Status != "queued" {
		return fmt.Errorf("APKG export requires id, session, user, and queued status")
	}
	tx, err := s.store.pg.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return fmt.Errorf("begin APKG export transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `
		INSERT INTO kc_apkg_exports (export_id, session_id, user_id, template_id, deck_name, package_name, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, export.ExportID, export.SessionID, export.UserID, export.TemplateID, export.DeckName, export.PackageName, export.Status); err != nil {
		return fmt.Errorf("create APKG export: %w", err)
	}
	client, err := river.NewClient(riverpgxv5.New(s.store.pg), &river.Config{SkipUnknownJobCheck: true})
	if err != nil {
		return fmt.Errorf("create River export client: %w", err)
	}
	if _, err := client.InsertTx(ctx, tx, repo.APKGExportJobArgs{ExportID: export.ExportID}, &river.InsertOpts{
		Queue: APKGExportQueue,
		UniqueOpts: river.UniqueOpts{
			ByArgs: true,
		},
	}); err != nil {
		return fmt.Errorf("enqueue APKG export: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit APKG export transaction: %w", err)
	}
	return nil
}

// NewAPKGExportWorkerClient builds the process-local River consumer. Producers
// remain independent so requests can be queued even while no worker is alive.
func NewAPKGExportWorkerClient(store *SessionStore, worker river.Worker[repo.APKGExportJobArgs]) (*river.Client[pgx.Tx], error) {
	if store == nil || store.pg == nil {
		return nil, fmt.Errorf("APKG export worker postgres unavailable")
	}
	if worker == nil {
		return nil, fmt.Errorf("APKG export worker is required")
	}
	workers := river.NewWorkers()
	river.AddWorker(workers, worker)
	return river.NewClient(riverpgxv5.New(store.pg), &river.Config{
		Queues: map[string]river.QueueConfig{
			APKGExportQueue: {MaxWorkers: 2},
		},
		Workers:     workers,
		JobTimeout:  2 * time.Minute,
		MaxAttempts: 5,
	})
}
