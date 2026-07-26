package persistent

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/google/uuid"

	"task-orchestrator/internal/usecase"
)

func TestConversationDispatchOutbox_IdempotencyAndStaleReclaim(t *testing.T) {
	pool := requireTestPostgres(t)
	defer pool.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	var exists bool
	if err := pool.QueryRow(ctx, `SELECT to_regclass('public.kc_conversation_dispatch_outbox') IS NOT NULL`).Scan(&exists); err != nil {
		t.Fatalf("inspect conversation outbox migration: %v", err)
	}
	if !exists {
		t.Skip("conversation outbox migration is not applied")
	}

	suffix := time.Now().UTC().UnixNano()
	threadID := fmt.Sprintf("outbox_%d", suffix)
	dispatchID := uuid.NewString()
	if _, err := pool.Exec(ctx, `INSERT INTO kc_sessions (session_id, user_id) VALUES ($1, $2)`, threadID, "it-user"); err != nil {
		t.Fatalf("insert test session: %v", err)
	}
	defer func() {
		_, _ = pool.Exec(context.Background(), `DELETE FROM kc_sessions WHERE session_id = $1`, threadID)
	}()

	store := &SessionStore{pg: pool}
	item := usecase.ConversationDispatch{
		DispatchID: dispatchID, IdempotencyKey: "start:" + dispatchID,
		ThreadID: threadID, RunID: "run-" + dispatchID, ProcessID: "process-" + dispatchID,
		AccountID: "it-user", ProjectID: threadID, Kind: "start",
		Payload: []byte(`{"start":{"run_id":"process"}}`), CreatedAt: time.Now().UTC(),
	}
	if err := store.EnqueueConversationDispatch(ctx, item); err != nil {
		t.Fatalf("enqueue dispatch: %v", err)
	}
	duplicate := item
	duplicate.DispatchID = uuid.NewString()
	if err := store.EnqueueConversationDispatch(ctx, duplicate); err != nil {
		t.Fatalf("enqueue duplicate dispatch: %v", err)
	}

	var count int
	if err := pool.QueryRow(ctx, `SELECT COUNT(*) FROM kc_conversation_dispatch_outbox WHERE idempotency_key = $1`, item.IdempotencyKey).Scan(&count); err != nil {
		t.Fatalf("count dispatches: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected one idempotent dispatch row, got %d", count)
	}

	claimed, err := store.ClaimConversationDispatches(ctx, 100, time.Minute)
	if err != nil {
		t.Fatalf("claim dispatch: %v", err)
	}
	first, ok := findClaimedDispatch(claimed, dispatchID)
	if !ok || first.Attempts != 1 {
		t.Fatalf("unexpected first claim: %#v", claimed)
	}
	if _, err := pool.Exec(ctx, `UPDATE kc_conversation_dispatch_outbox SET updated_at = NOW() - INTERVAL '2 minutes' WHERE dispatch_id = $1`, dispatchID); err != nil {
		t.Fatalf("age dispatch lease: %v", err)
	}
	claimed, err = store.ClaimConversationDispatches(ctx, 100, time.Minute)
	if err != nil {
		t.Fatalf("reclaim stale dispatch: %v", err)
	}
	second, ok := findClaimedDispatch(claimed, dispatchID)
	if !ok || second.Attempts != 2 {
		t.Fatalf("unexpected stale reclaim: %#v", claimed)
	}

	if err := store.RetryConversationDispatch(ctx, dispatchID, "temporary", time.Now().UTC().Add(-time.Second)); err != nil {
		t.Fatalf("schedule retry: %v", err)
	}
	claimed, err = store.ClaimConversationDispatches(ctx, 100, time.Minute)
	if err != nil {
		t.Fatalf("claim retried dispatch: %v", err)
	}
	third, ok := findClaimedDispatch(claimed, dispatchID)
	if !ok || third.Attempts != 3 {
		t.Fatalf("unexpected retry claim: %#v", claimed)
	}
	if err := store.MarkConversationDispatchDone(ctx, dispatchID); err != nil {
		t.Fatalf("mark dispatch done: %v", err)
	}
	var status string
	if err := pool.QueryRow(ctx, `SELECT status FROM kc_conversation_dispatch_outbox WHERE dispatch_id = $1`, dispatchID).Scan(&status); err != nil {
		t.Fatalf("read dispatch status: %v", err)
	}
	if status != "dispatched" {
		t.Fatalf("expected dispatched status, got %q", status)
	}
}

func findClaimedDispatch(items []usecase.ConversationDispatch, dispatchID string) (usecase.ConversationDispatch, bool) {
	for _, item := range items {
		if item.DispatchID == dispatchID {
			return item, true
		}
	}
	return usecase.ConversationDispatch{}, false
}
