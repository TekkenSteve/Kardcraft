package v1

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
)

func TestSSEHandlerReplaysDurableEventsAfterCursor(t *testing.T) {
	feed := &fakeExecutionEventFeed{events: []usecase.TaskExecutionEvent{{
		EventID:   "event-7",
		EventType: "run.completed",
		RunID:     "run-1",
		Sequence:  7,
		Timestamp: time.Date(2026, 7, 15, 0, 0, 0, 0, time.UTC),
		Payload:   map[string]any{"result": "ok"},
	}}}
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(_ http.ResponseWriter, status int, code, message string, details map[string]any) {
			t.Fatalf("unexpected authorization error: %d %s", status, code)
		},
		UserID:          func(*http.Request) string { return "user-1" },
		Authorize:       func(*http.Request, string, string) bool { return true },
		Feed:            feed,
		AuthzDeniedCode: "authz-denied",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/stream/sse?workflow_id=task-1&last_event_id=6", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if feed.afterSequence != 6 {
		t.Fatalf("after sequence = %d, want 6", feed.afterSequence)
	}
	if !strings.Contains(rr.Body.String(), "id: 7") || !strings.Contains(rr.Body.String(), "event: run.completed") {
		t.Fatalf("expected durable event in SSE response, got %q", rr.Body.String())
	}
}

func TestSSEHandlerRejectsUnauthorizedTask(t *testing.T) {
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			w.WriteHeader(status)
		},
		UserID:          func(*http.Request) string { return "user-1" },
		Authorize:       func(*http.Request, string, string) bool { return false },
		Feed:            &fakeExecutionEventFeed{},
		AuthzDeniedCode: "authz-denied",
	})
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/api/v1/stream/sse?workflow_id=task-1", nil))
	if rr.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusForbidden)
	}
}

type fakeExecutionEventFeed struct {
	afterSequence int64
	events        []usecase.TaskExecutionEvent
}

func (f *fakeExecutionEventFeed) Subscribe(_ context.Context, _ string, afterSequence int64) (usecase.TaskExecutionSubscription, error) {
	f.afterSequence = afterSequence
	channel := make(chan usecase.TaskExecutionEvent, len(f.events))
	for _, event := range f.events {
		channel <- event
	}
	close(channel)
	return fakeExecutionEventSubscription{events: channel}, nil
}

type fakeExecutionEventSubscription struct {
	events <-chan usecase.TaskExecutionEvent
}

func (s fakeExecutionEventSubscription) Events() <-chan usecase.TaskExecutionEvent { return s.events }
func (fakeExecutionEventSubscription) Close() error                                { return nil }
