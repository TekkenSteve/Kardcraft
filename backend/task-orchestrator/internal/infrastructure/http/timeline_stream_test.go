package httpserver

import (
	"context"
	"encoding/json"
	"sync/atomic"
	"testing"
	"time"

	redissvc "task-orchestrator/internal/infrastructure/redis"
)

func TestBuildUsageLedgerRowRejectsSchemaMismatch(t *testing.T) {
	payload := map[string]any{
		"schema_version": "2",
		"idempotency_key": "task-1:req-1",
		"task_id": "task-1",
		"provider": "openai",
		"model": "gpt-4o-mini",
	}
	_, ok, reason := buildUsageLedgerRow(payload, "wf-1", "task-1", "sess-1")
	if ok {
		t.Fatalf("expected schema mismatch to be rejected")
	}
	if reason != "schema_mismatch" {
		t.Fatalf("expected reason schema_mismatch, got %s", reason)
	}
}

func TestBuildUsageLedgerRowRejectsMalformedPayload(t *testing.T) {
	payload := map[string]any{
		"schema_version": "1",
		"task_id":        "task-1",
		"provider":       "openai",
		// model and idempotency_key intentionally missing
	}
	_, ok, reason := buildUsageLedgerRow(payload, "wf-1", "task-1", "sess-1")
	if ok {
		t.Fatalf("expected malformed payload to be rejected")
	}
	if reason != "missing_idempotency_key" {
		t.Fatalf("expected reason missing_idempotency_key, got %s", reason)
	}
}

type fakeRedisStreamClient struct {
	enabled   bool
	readCalls atomic.Int64
}

func (f *fakeRedisStreamClient) Enabled() bool { return f.enabled }

func (f *fakeRedisStreamClient) StreamRead(ctx context.Context, workflowID, fromID string, count int64, block time.Duration) ([]redissvc.StreamEntry, string, error) {
	f.readCalls.Add(1)
	<-ctx.Done()
	return nil, fromID, ctx.Err()
}

func (f *fakeRedisStreamClient) GetCheckpoint(ctx context.Context, workflowID string) (string, error) {
	return "", nil
}

func (f *fakeRedisStreamClient) SetCheckpoint(ctx context.Context, workflowID, streamID string) error {
	return nil
}

func (f *fakeRedisStreamClient) Stats() redissvc.Stats { return redissvc.Stats{} }

func newTestServer(redisClient redisStreamClient) *Server {
	return &Server{
		redisSvc:           redisClient,
		timelineByWorkflow: make(map[string][]TimelineEvent),
		uploads:            make(map[string]*uploadState),
		subscribers:        make(map[string]map[int]chan sseEvent),
		streamReaders:      make(map[string]context.CancelFunc),
		seenStreamIDs:      make(map[string]map[string]struct{}),
	}
}

func waitFor(t *testing.T, timeout time.Duration, fn func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if fn() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("condition not met within %s", timeout)
}

func TestAppendTimelineDedupeByStreamID(t *testing.T) {
	s := newTestServer(nil)
	wf := "wf-dedupe"

	s.appendTimelineWithStreamID(wf, "", "NODE_STARTED", "started", "1-1", map[string]any{"node_name": "n1"})
	s.appendTimelineWithStreamID(wf, "", "NODE_STARTED", "started", "1-1", map[string]any{"node_name": "n1"})

	if got := len(s.timelineByWorkflow[wf]); got != 1 {
		t.Fatalf("expected 1 timeline event, got %d", got)
	}
	if got := atomic.LoadInt64(&s.duplicateDrops); got != 1 {
		t.Fatalf("expected duplicateDrops=1, got %d", got)
	}
}

func TestAppendTimelinePublishesPayloadContract(t *testing.T) {
	s := newTestServer(nil)
	wf := "wf-payload"
	subID, ch := s.subscribe(wf)
	defer s.unsubscribe(wf, subID)

	inputPayload := map[string]any{
		"node_name": "compose_cards",
		"detail":    map[string]any{"count": 2},
	}
	s.appendTimelineWithStreamID(wf, "", "NODE_COMPLETED", "done", "2-1", inputPayload)

	select {
	case ev := <-ch:
		var out map[string]any
		if err := json.Unmarshal(ev.payload, &out); err != nil {
			t.Fatalf("unmarshal payload: %v", err)
		}
		if out["type"] != "NODE_COMPLETED" {
			t.Fatalf("expected type NODE_COMPLETED, got %v", out["type"])
		}
		if out["workflow_id"] != wf {
			t.Fatalf("expected workflow_id %s, got %v", wf, out["workflow_id"])
		}
		if out["payload"] == nil {
			t.Fatalf("expected payload to be present")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for SSE event")
	}
}

func TestWorkflowStreamReaderLifecycle(t *testing.T) {
	fake := &fakeRedisStreamClient{enabled: true}
	s := newTestServer(fake)
	wf := "wf-reader"

	s.ensureWorkflowStreamReader(wf)
	waitFor(t, 2*time.Second, func() bool {
		s.mu.RLock()
		defer s.mu.RUnlock()
		_, ok := s.streamReaders[wf]
		return ok
	})
	waitFor(t, 2*time.Second, func() bool {
		return fake.readCalls.Load() > 0
	})

	s.stopWorkflowStreamReader(wf)
	waitFor(t, 2*time.Second, func() bool {
		s.mu.RLock()
		defer s.mu.RUnlock()
		_, ok := s.streamReaders[wf]
		return !ok
	})
	s.mu.RLock()
	_, seen := s.seenStreamIDs[wf]
	s.mu.RUnlock()
	if seen {
		t.Fatalf("expected seenStreamIDs[%s] removed", wf)
	}
}
