package restapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestParseLastEventID(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  int64
	}{
		{name: "empty", input: "", want: 0},
		{name: "invalid", input: "abc", want: 0},
		{name: "negative", input: "-1", want: 0},
		{name: "valid", input: "42", want: 42},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := parseLastEventID(tt.input)
			if got != tt.want {
				t.Fatalf("parseLastEventID(%q) = %d, want %d", tt.input, got, tt.want)
			}
		})
	}
}

func TestResolveLastEventID(t *testing.T) {
	t.Run("prefers query", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1&last_event_id=123", nil)
		req.Header.Set("Last-Event-ID", "456")
		got, ok := resolveLastEventID(req)
		if !ok {
			t.Fatalf("expected query cursor to be present")
		}
		if got != 123 {
			t.Fatalf("expected query cursor 123, got %d", got)
		}
	})

	t.Run("falls back to header", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1", nil)
		req.Header.Set("Last-Event-ID", "456")
		got, ok := resolveLastEventID(req)
		if !ok {
			t.Fatalf("expected header cursor to be present")
		}
		if got != 456 {
			t.Fatalf("expected header cursor 456, got %d", got)
		}
	})

	t.Run("keeps explicit zero query cursor", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1&last_event_id=0", nil)
		got, ok := resolveLastEventID(req)
		if !ok {
			t.Fatalf("expected zero query cursor to be present")
		}
		if got != 0 {
			t.Fatalf("expected query cursor 0, got %d", got)
		}
	})
}

func TestSSEHandlerPassesCursorToBacklog(t *testing.T) {
	var capturedAfterEventID int64
	backlogCalled := false
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			t.Fatalf("unexpected api error status=%d code=%s", status, code)
		},
		UserID:     func(r *http.Request) string { return "u1" },
		Authorize:  func(r *http.Request, userID, workflowID string) bool { return true },
		NowRFC3339: func() string { return "2026-04-24T00:00:00Z" },
		Subscribe: func(workflowID string) (int, chan OutboundEvent) {
			ch := make(chan OutboundEvent)
			close(ch)
			return 1, ch
		},
		Unsubscribe:                func(workflowID string, subscriberID int) {},
		EnsureWorkflowStreamReader: func(workflowID string) {},
		Backlog: func(workflowID string, afterEventID int64) []map[string]any {
			backlogCalled = true
			capturedAfterEventID = afterEventID
			return nil
		},
		AuthzDeniedCode: "authz-denied",
	})

	req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1&last_event_id=123", nil)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)
	if !backlogCalled {
		t.Fatalf("expected backlog to be called")
	}
	if capturedAfterEventID != 123 {
		t.Fatalf("expected cursor 123, got %d", capturedAfterEventID)
	}
}

func TestSSEHandlerPassesZeroCursorToBacklog(t *testing.T) {
	var capturedAfterEventID int64 = -1
	backlogCalled := false
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			t.Fatalf("unexpected api error status=%d code=%s", status, code)
		},
		UserID:     func(r *http.Request) string { return "u1" },
		Authorize:  func(r *http.Request, userID, workflowID string) bool { return true },
		NowRFC3339: func() string { return "2026-04-24T00:00:00Z" },
		Subscribe: func(workflowID string) (int, chan OutboundEvent) {
			ch := make(chan OutboundEvent)
			close(ch)
			return 1, ch
		},
		Unsubscribe:                func(workflowID string, subscriberID int) {},
		EnsureWorkflowStreamReader: func(workflowID string) {},
		Backlog: func(workflowID string, afterEventID int64) []map[string]any {
			backlogCalled = true
			capturedAfterEventID = afterEventID
			return nil
		},
		AuthzDeniedCode: "authz-denied",
	})

	req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1&last_event_id=0", nil)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)
	if !backlogCalled {
		t.Fatalf("expected backlog to be called")
	}
	if capturedAfterEventID != 0 {
		t.Fatalf("expected cursor 0, got %d", capturedAfterEventID)
	}
}

func TestSSEHandlerSkipsBacklogWithoutCursor(t *testing.T) {
	backlogCalled := false
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			t.Fatalf("unexpected api error status=%d code=%s", status, code)
		},
		UserID:     func(r *http.Request) string { return "u1" },
		Authorize:  func(r *http.Request, userID, workflowID string) bool { return true },
		NowRFC3339: func() string { return "2026-04-24T00:00:00Z" },
		Subscribe: func(workflowID string) (int, chan OutboundEvent) {
			ch := make(chan OutboundEvent)
			close(ch)
			return 1, ch
		},
		Unsubscribe:                func(workflowID string, subscriberID int) {},
		EnsureWorkflowStreamReader: func(workflowID string) {},
		Backlog: func(workflowID string, afterEventID int64) []map[string]any {
			backlogCalled = true
			return nil
		},
		AuthzDeniedCode: "authz-denied",
	})

	req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if backlogCalled {
		t.Fatalf("expected backlog to be skipped when cursor is absent")
	}
}

func TestSSEHandlerWritesBacklogEventID(t *testing.T) {
	handler := NewSSEHandler(SSEDeps{
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			t.Fatalf("unexpected api error status=%d code=%s", status, code)
		},
		UserID:     func(r *http.Request) string { return "u1" },
		Authorize:  func(r *http.Request, userID, workflowID string) bool { return true },
		NowRFC3339: func() string { return "2026-04-24T00:00:00Z" },
		Subscribe: func(workflowID string) (int, chan OutboundEvent) {
			ch := make(chan OutboundEvent)
			close(ch)
			return 1, ch
		},
		Unsubscribe:                func(workflowID string, subscriberID int) {},
		EnsureWorkflowStreamReader: func(workflowID string) {},
		Backlog: func(workflowID string, afterEventID int64) []map[string]any {
			return []map[string]any{
				{
					"event_id":    int64(7),
					"event_type":  "WORKFLOW_STARTED",
					"workflow_id": workflowID,
				},
			}
		},
		AuthzDeniedCode: "authz-denied",
	})

	req := httptest.NewRequest("GET", "/api/v1/stream/sse?workflow_id=wf-1&last_event_id=1", nil)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)
	body := rr.Body.String()
	if !strings.Contains(body, "id: 7") {
		t.Fatalf("expected backlog event id line, body=%q", body)
	}
}
