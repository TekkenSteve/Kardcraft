package restapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestWithAuth_RequiresGatewayIdentityForAPIPaths(t *testing.T) {
	s := &Server{httpClient: &http.Client{Timeout: 200 * time.Millisecond}}
	protected := s.withAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions", nil)
	rr := httptest.NewRecorder()

	protected.ServeHTTP(rr, req)

	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d body=%s", rr.Code, rr.Body.String())
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeUnauthenticated {
		t.Fatalf("expected code %s, got %s", errCodeUnauthenticated, payload.Error.Code)
	}
}

func TestWithAuth_AllowsHealthWithoutCredentials(t *testing.T) {
	s := &Server{httpClient: &http.Client{Timeout: 200 * time.Millisecond}}
	handler := s.withAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := userIDFromContext(r.Context()); got != "" {
			t.Fatalf("expected empty user on non-auth route, got %q", got)
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	}))
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
}

func TestWithAuth_UsesGatewayIdentityHeader(t *testing.T) {
	s := &Server{httpClient: &http.Client{Timeout: 200 * time.Millisecond}}
	handler := s.withAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"user_id": userIDFromContext(r.Context())})
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions", nil)
	req.Header.Set("X-User-Id", "user-123")
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["user_id"] != "user-123" {
		t.Fatalf("expected user_id=user-123, got %#v", body["user_id"])
	}
}

func TestWithAuth_HonorsInjectedContextUserForUnitTests(t *testing.T) {
	s := &Server{httpClient: &http.Client{Timeout: 200 * time.Millisecond}}
	handler := s.withAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"user_id": userIDFromContext(r.Context())})
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions", nil)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u-test"))
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["user_id"] != "u-test" {
		t.Fatalf("expected user_id=u-test, got %#v", body["user_id"])
	}
}
