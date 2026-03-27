package httpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func decodeAPIErrorBody(t *testing.T, body string) apiErrorBody {
	t.Helper()
	var payload apiErrorBody
	if err := json.Unmarshal([]byte(body), &payload); err != nil {
		t.Fatalf("decode error payload failed: %v body=%s", err, body)
	}
	return payload
}

func TestAuthorizeTaskAccess_FalseWhenStoreUnavailable(t *testing.T) {
	s := &Server{}
	if got := s.authorizeTaskAccess(t.Context(), "u1", "t1"); got {
		t.Fatalf("expected false when session store is unavailable")
	}
}

func TestHandleGetTask_ReturnsAuthzDeniedWithoutOwnership(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/task-1", nil)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestWorkflowStatus_ReturnsAuthzDeniedWithoutOwnership(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/workflows/status?workflow_id=wf-1", nil)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestWorkflowCancel_ReturnsAuthzDeniedWithoutOwnership(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/workflows/cancel", strings.NewReader(`{"workflow_id":"wf-1","reason":"x"}`))
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestWorkflowHistory_ReturnsAuthzDeniedWithoutOwnership(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/workflows/history?workflow_id=wf-1", nil)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestTaskControl_ReturnsAuthzDeniedWithoutOwnership(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/tasks/task-1/pause", strings.NewReader(`{"reason":"x"}`))
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestSSEHandler_ReturnsAuthzDeniedBeforeSubscribe(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/stream/sse?workflow_id=wf-1", nil)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeAuthzDenied {
		t.Fatalf("expected %s, got %s", errCodeAuthzDenied, payload.Error.Code)
	}
}

func TestSessionControl_RequiresIdempotencyKey(t *testing.T) {
	s := newAuthzRouteServer()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sessions/s1/pause", strings.NewReader(`{}`))
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rr.Code)
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeIdempotencyKeyRequired {
		t.Fatalf("expected %s, got %s", errCodeIdempotencyKeyRequired, payload.Error.Code)
	}
}

func newAuthzRouteServer() *Server {
	s := &Server{mux: http.NewServeMux()}
	s.registerRoutes()
	return s
}
