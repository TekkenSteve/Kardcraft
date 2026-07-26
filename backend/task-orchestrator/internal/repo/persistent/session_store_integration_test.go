package persistent

import (
	"context"
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func requireTestPostgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("TEST_POSTGRES_DSN not set; skipping integration test")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pgxpool.New failed: %v", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		t.Fatalf("postgres ping failed: %v", err)
	}
	return pool
}

func ensureKCTasksTable(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	_, err := pool.Exec(ctx, `
CREATE TABLE IF NOT EXISTS kc_tasks (
    task_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    task_type VARCHAR,
    status VARCHAR,
    query TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    result JSONB,
    completed_at TIMESTAMPTZ
)`)
	if err != nil {
		t.Fatalf("ensure kc_tasks table failed: %v", err)
	}
}

func TestInsertTaskIfNoActive_ConcurrentSingleWinner(t *testing.T) {
	pool := requireTestPostgres(t)
	defer pool.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	ensureKCTasksTable(t, ctx, pool)

	store := &SessionStore{pg: pool}
	sessionID := fmt.Sprintf("it_session_%d", time.Now().UTC().UnixNano())
	userID := "it_user"
	if _, err := pool.Exec(ctx, `INSERT INTO kc_sessions (session_id, user_id) VALUES ($1, $2)`, sessionID, userID); err != nil {
		t.Fatalf("insert test session failed: %v", err)
	}
	defer func() {
		_, _ = pool.Exec(context.Background(), `DELETE FROM kc_sessions WHERE session_id = $1`, sessionID)
	}()

	if _, err := pool.Exec(ctx, `DELETE FROM kc_tasks WHERE session_id = $1 AND user_id = $2`, sessionID, userID); err != nil {
		t.Fatalf("cleanup failed: %v", err)
	}

	const workers = 12
	var started sync.WaitGroup
	started.Add(workers)
	start := make(chan struct{})
	var insertedCount atomic.Int64
	var wg sync.WaitGroup
	wg.Add(workers)

	for i := 0; i < workers; i++ {
		i := i
		go func() {
			defer wg.Done()
			taskID := fmt.Sprintf("it_task_%d_%d", time.Now().UTC().UnixNano(), i)
			started.Done()
			<-start
			inserted, err := store.InsertTaskIfNoActive(ctx, taskID, sessionID, userID, "main", "pending", "q")
			if err != nil {
				t.Errorf("insert failed: %v", err)
				return
			}
			if inserted {
				insertedCount.Add(1)
			}
		}()
	}

	started.Wait()
	close(start)
	wg.Wait()

	if got := insertedCount.Load(); got != 1 {
		t.Fatalf("expected exactly one inserted task, got %d", got)
	}

	var activeCount int
	if err := pool.QueryRow(ctx, `
SELECT COUNT(*) FROM kc_tasks
WHERE session_id = $1 AND user_id = $2
  AND LOWER(COALESCE(status::text, '')) IN ('pending','queued','running','paused')
`, sessionID, userID).Scan(&activeCount); err != nil {
		t.Fatalf("active count query failed: %v", err)
	}
	if activeCount != 1 {
		t.Fatalf("expected one active row, got %d", activeCount)
	}
}

func TestInsertTaskIfNoActive_AllowsNewTaskAfterTerminalState(t *testing.T) {
	pool := requireTestPostgres(t)
	defer pool.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	ensureKCTasksTable(t, ctx, pool)

	store := &SessionStore{pg: pool}
	sessionID := fmt.Sprintf("it_session_term_%d", time.Now().UTC().UnixNano())
	userID := "it_user"
	taskID1 := fmt.Sprintf("it_task_first_%d", time.Now().UTC().UnixNano())
	taskID2 := fmt.Sprintf("it_task_second_%d", time.Now().UTC().UnixNano())
	if _, err := pool.Exec(ctx, `INSERT INTO kc_sessions (session_id, user_id) VALUES ($1, $2)`, sessionID, userID); err != nil {
		t.Fatalf("insert test session failed: %v", err)
	}
	defer func() {
		_, _ = pool.Exec(context.Background(), `DELETE FROM kc_sessions WHERE session_id = $1`, sessionID)
	}()

	if _, err := pool.Exec(ctx, `DELETE FROM kc_tasks WHERE session_id = $1 AND user_id = $2`, sessionID, userID); err != nil {
		t.Fatalf("cleanup failed: %v", err)
	}

	inserted, err := store.InsertTaskIfNoActive(ctx, taskID1, sessionID, userID, "main", "running", "q1")
	if err != nil {
		t.Fatalf("first insert failed: %v", err)
	}
	if !inserted {
		t.Fatalf("expected first insert to succeed")
	}

	if err := store.UpdateTaskStatus(ctx, taskID1, "completed", ""); err != nil {
		t.Fatalf("update to terminal failed: %v", err)
	}

	inserted, err = store.InsertTaskIfNoActive(ctx, taskID2, sessionID, userID, "main", "pending", "q2")
	if err != nil {
		t.Fatalf("second insert failed: %v", err)
	}
	if !inserted {
		t.Fatalf("expected second insert after terminal state to succeed")
	}
}
