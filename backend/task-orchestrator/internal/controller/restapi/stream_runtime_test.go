package restapi

import (
	"context"
	"encoding/json"
	"sync/atomic"
	"testing"
	"time"
)

func TestBuildUsageLedgerRowRejectsLegacyFlatPayload(t *testing.T) {
	payload := map[string]any{
		"idempotency_key": "task-1:req-1",
		"task_id":         "task-1",
		"provider":        "openai",
		"model":           "gpt-4o-mini",
	}
	_, ok, reason := BuildUsageLedgerRow(payload, "wf-1", "task-1", "sess-1")
	if ok {
		t.Fatalf("expected legacy payload to be rejected")
	}
	if reason != "missing_usage_payload" {
		t.Fatalf("expected reason missing_usage_payload, got %s", reason)
	}
}

func TestBuildUsageLedgerRowRejectsMalformedPayload(t *testing.T) {
	payload := map[string]any{
		"event_id":    "evt-malformed-1",
		"occurred_at": "2026-04-16T08:00:00Z",
		"task_id":     "task-1",
		"usage": map[string]any{
			"provider":   "openai",
			"created_at": "2026-04-16T08:00:00Z",
			// model and idempotency_key intentionally missing
		},
	}
	_, ok, reason := BuildUsageLedgerRow(payload, "wf-1", "task-1", "sess-1")
	if ok {
		t.Fatalf("expected malformed payload to be rejected")
	}
	if reason != "missing_idempotency_key" {
		t.Fatalf("expected reason missing_idempotency_key, got %s", reason)
	}
}

func TestBuildUsageLedgerRowAcceptsUsageEnvelope(t *testing.T) {
	payload := map[string]any{
		"event_id":    "evt-1",
		"occurred_at": "2026-04-16T08:00:00Z",
		"task_id":     "task-1",
		"workflow_id": "wf-1",
		"session_id":  "sess-1",
		"user_id":     "user-1",
		"usage": map[string]any{
			"idempotency_key":     "task-1:req-1",
			"operation":           "acompletion",
			"intent":              "chat",
			"provider":            "openai",
			"model":               "openai/gpt-4o-mini",
			"prompt_tokens":       8,
			"completion_tokens":   4,
			"cache_read_tokens":   0,
			"cache_write_tokens":  0,
			"total_tokens":        12,
			"input_cost_usd":      0.0008,
			"output_cost_usd":     0.0012,
			"cache_cost_usd":      0.0,
			"total_cost_usd":      0.002,
			"estimated":           false,
			"source":              "provider",
			"external_request_id": "req-1",
			"created_at":          "2026-04-16T08:00:00Z",
		},
	}
	row, ok, reason := BuildUsageLedgerRow(payload, "wf-1", "task-1", "sess-1")
	if !ok {
		t.Fatalf("expected envelope payload to be accepted, got reason=%s", reason)
	}
	if row.TaskID != "task-1" || row.Provider != "openai" || row.Model != "openai/gpt-4o-mini" {
		t.Fatalf("unexpected row identity fields: %+v", row)
	}
	if row.TotalTokens != 12 {
		t.Fatalf("expected total tokens 12, got %d", row.TotalTokens)
	}
	if row.TotalCostUSD != 0.002 {
		t.Fatalf("expected total_cost_usd to match authoritative payload, got %f", row.TotalCostUSD)
	}
	if row.InputCostUSD != 0.0008 || row.OutputCostUSD != 0.0012 {
		t.Fatalf("expected cost breakdown from authoritative payload, got input=%f output=%f", row.InputCostUSD, row.OutputCostUSD)
	}
}

func TestBuildUsageLedgerRowRejectsMissingAuthoritativeCost(t *testing.T) {
	payload := map[string]any{
		"event_id":    "evt-2",
		"occurred_at": "2026-04-16T08:00:00Z",
		"task_id":     "task-2",
		"workflow_id": "wf-2",
		"session_id":  "sess-2",
		"user_id":     "user-2",
		"usage": map[string]any{
			"idempotency_key":     "task-2:req-2",
			"operation":           "acompletion",
			"intent":              "chat",
			"provider":            "openai",
			"model":               "gpt-4o-mini",
			"prompt_tokens":       10,
			"completion_tokens":   5,
			"total_tokens":        15,
			"estimated":           false,
			"source":              "provider",
			"external_request_id": "req-2",
			"created_at":          "2026-04-16T08:00:00Z",
		},
	}
	_, ok, reason := BuildUsageLedgerRow(payload, "wf-2", "task-2", "sess-2")
	if ok {
		t.Fatalf("expected payload without authoritative cost to be rejected")
	}
	if reason != "missing_authoritative_cost" {
		t.Fatalf("expected reason missing_authoritative_cost, got %s", reason)
	}
}

func TestBuildUsageLedgerRowAcceptsUnknownFieldsForForwardCompatibility(t *testing.T) {
	payload := map[string]any{
		"event_id":     "evt-3",
		"occurred_at":  "2026-04-16T08:00:00Z",
		"task_id":      "task-3",
		"workflow_id":  "wf-3",
		"session_id":   "sess-3",
		"user_id":      "user-3",
		"future_field": "new-value",
		"usage": map[string]any{
			"idempotency_key":     "task-3:req-3",
			"operation":           "acompletion",
			"intent":              "chat",
			"provider":            "openai",
			"model":               "openai/gpt-4o-mini",
			"prompt_tokens":       10,
			"completion_tokens":   5,
			"cache_read_tokens":   0,
			"cache_write_tokens":  0,
			"total_tokens":        15,
			"input_cost_usd":      0.001,
			"output_cost_usd":     0.002,
			"cache_cost_usd":      0.0,
			"total_cost_usd":      0.003,
			"estimated":           false,
			"source":              "provider",
			"external_request_id": "req-3",
			"created_at":          "2026-04-16T08:00:00Z",
			"future_usage_field":  "compatible",
		},
	}
	row, ok, reason := BuildUsageLedgerRow(payload, "wf-3", "task-3", "sess-3")
	if !ok {
		t.Fatalf("expected payload with unknown fields to be accepted, got reason=%s", reason)
	}
	if row.TotalCostUSD != 0.003 {
		t.Fatalf("expected authoritative total cost 0.003, got %f", row.TotalCostUSD)
	}
}

type fakeRedisStreamClient struct {
	enabled   bool
	readCalls atomic.Int64
}

func (f *fakeRedisStreamClient) Enabled() bool { return f.enabled }

func (f *fakeRedisStreamClient) Stats() map[string]any { return map[string]any{} }

func newTestServer(redisClient redisStreamClient) *Server {
	return &Server{
		redisSvc:                redisClient,
		timelineByWorkflow:      make(map[string][]TimelineEvent),
		uploads:                 make(map[string]*uploadState),
		subscribers:             make(map[string]map[int]chan OutboundEvent),
		streamReaders:           make(map[string]context.CancelFunc),
		seenStreamIDs:           make(map[string]map[string]struct{}),
		runSeqByRunID:           make(map[string]int64),
		workflowRunByWorkflowID: make(map[string]string),
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
	runID := "run-dedupe"
	s.bindWorkflowRunID(wf, runID)

	s.appendTimelineWithStreamID(wf, "", "NODE_STARTED", "started", "1-1", map[string]any{"node_name": "n1", "run_id": runID, "correlation_id": "corr-1"})
	s.appendTimelineWithStreamID(wf, "", "NODE_STARTED", "started", "1-1", map[string]any{"node_name": "n1", "run_id": runID, "correlation_id": "corr-1"})

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
		"node_name":      "compose_cards",
		"detail":         map[string]any{"count": 2},
		"run_id":         "run-123",
		"correlation_id": "corr-2",
	}
	s.appendTimelineWithStreamID(wf, "", "NODE_COMPLETED", "done", "2-1", inputPayload)

	select {
	case ev := <-ch:
		var out map[string]any
		if err := json.Unmarshal(ev.Payload, &out); err != nil {
			t.Fatalf("unmarshal payload: %v", err)
		}
		if out["event_type"] != "NODE_COMPLETED" {
			t.Fatalf("expected event_type NODE_COMPLETED, got %v", out["event_type"])
		}
		if out["workflow_id"] != wf {
			t.Fatalf("expected workflow_id %s, got %v", wf, out["workflow_id"])
		}
		if out["run_id"] != "run-123" {
			t.Fatalf("expected run_id run-123, got %v", out["run_id"])
		}
		if seq, ok := out["seq"].(float64); !ok || seq != 1 {
			t.Fatalf("expected seq 1, got %#v", out["seq"])
		}
		if out["payload"] == nil {
			t.Fatalf("expected payload to be present")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for SSE event")
	}
}

func TestAppendTimelineRunSeqMonotonic(t *testing.T) {
	s := newTestServer(nil)
	wf := "wf-seq"
	runID := "run-seq-1"

	s.bindWorkflowRunID(wf, runID)
	s.appendTimelineWithStreamID(wf, "session-1", "NODE_STARTED", "start", "3-1", map[string]any{"run_id": runID, "correlation_id": "corr-3"})
	s.appendTimelineWithStreamID(wf, "session-1", "NODE_COMPLETED", "done", "3-2", map[string]any{"run_id": runID, "correlation_id": "corr-3"})

	events := s.timelineByWorkflow[wf]
	if len(events) != 2 {
		t.Fatalf("expected 2 timeline events, got %d", len(events))
	}
	if events[0].Seq != 1 || events[1].Seq != 2 {
		t.Fatalf("expected seq to be monotonic [1,2], got [%d,%d]", events[0].Seq, events[1].Seq)
	}
}

func TestWorkflowStreamReaderSkipsWhenNoSubscriber(t *testing.T) {
	s := newTestServer(nil)
	wf := "wf-nosub"

	s.ensureWorkflowStreamReader(wf)

	s.mu.RLock()
	_, ok := s.streamReaders[wf]
	s.mu.RUnlock()
	if ok {
		t.Fatalf("expected no stream reader when streamSubscriber is nil")
	}
}
