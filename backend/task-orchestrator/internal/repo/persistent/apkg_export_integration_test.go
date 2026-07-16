package persistent

import (
	"context"
	"fmt"
	"testing"
	"time"

	"task-orchestrator/internal/repo"
)

func TestCreateAndEnqueueAPKGExportPersistsOneBusinessRecordAndRiverJob(t *testing.T) {
	pool := requireTestPostgres(t)
	defer pool.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	id := time.Now().UTC().UnixNano()
	sessionID := fmt.Sprintf("it_export_session_%d", id)
	exportID := fmt.Sprintf("it_export_%d", id)
	userID := "it_export_user"
	if _, err := pool.Exec(ctx, `INSERT INTO kc_sessions (session_id, user_id) VALUES ($1, $2)`, sessionID, userID); err != nil {
		t.Fatalf("create export session: %v", err)
	}
	t.Cleanup(func() {
		_, _ = pool.Exec(context.Background(), `DELETE FROM river_job WHERE kind = $1 AND args @> jsonb_build_object('export_id', $2::text)`, (repo.APKGExportJobArgs{}).Kind(), exportID)
		_, _ = pool.Exec(context.Background(), `DELETE FROM kc_sessions WHERE session_id = $1`, sessionID)
	})

	store := NewAPKGExportStore(&SessionStore{pg: pool})
	err := store.CreateAndEnqueueAPKGExport(ctx, repo.APKGExport{
		ExportID: exportID, SessionID: sessionID, UserID: userID, TemplateID: "template-1", Status: "queued",
	})
	if err != nil {
		t.Fatalf("CreateAndEnqueueAPKGExport: %v", err)
	}
	stored, found, err := store.GetAPKGExport(ctx, exportID, sessionID, userID)
	if err != nil || !found {
		t.Fatalf("GetAPKGExport found=%v err=%v", found, err)
	}
	if stored.Status != "queued" {
		t.Fatalf("export status = %q, want queued", stored.Status)
	}
	var jobCount int
	if err := pool.QueryRow(ctx, `SELECT COUNT(*) FROM river_job WHERE kind = $1 AND args @> jsonb_build_object('export_id', $2::text)`, (repo.APKGExportJobArgs{}).Kind(), exportID).Scan(&jobCount); err != nil {
		t.Fatalf("count River jobs: %v", err)
	}
	if jobCount != 1 {
		t.Fatalf("River job count = %d, want 1", jobCount)
	}
}
