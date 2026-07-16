// Package internalapi contains service-to-service HTTP adapters. These routes
// are intentionally separate from the user-facing v1 API.
package internalapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

const executionEventsPathPrefix = "/internal/execution/runs/"

type ServiceTokenValidator interface {
	Validate(ctx context.Context, token string) error
}

type ExecutionEventsDeps struct {
	Validator ServiceTokenValidator
	Execution usecase.TaskExecution
}

type executionEventRequest struct {
	EventID   string         `json:"event_id"`
	RunID     string         `json:"run_id"`
	ThreadID  string         `json:"thread_id,omitempty"`
	Sequence  int64          `json:"sequence"`
	EventType string         `json:"event_type"`
	Source    string         `json:"source"`
	Timestamp time.Time      `json:"timestamp"`
	Payload   map[string]any `json:"payload,omitempty"`
}

func NewExecutionEventsHandler(deps ExecutionEventsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if deps.Validator == nil || deps.Execution == nil {
			http.Error(w, "internal execution events unavailable", http.StatusServiceUnavailable)
			return
		}
		runID, ok := executionRunIDFromPath(r.URL.Path)
		if !ok {
			http.NotFound(w, r)
			return
		}
		if err := deps.Validator.Validate(r.Context(), bearerToken(r.Header.Get("Authorization"))); err != nil {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		var request executionEventRequest
		decoder := json.NewDecoder(r.Body)
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&request); err != nil {
			http.Error(w, "invalid event body", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(request.RunID) != runID {
			http.Error(w, "run_id in path and body must match", http.StatusBadRequest)
			return
		}
		if request.Payload == nil {
			request.Payload = map[string]any{}
		}
		stored, err := deps.Execution.IngestTaskExecutionEvent(r.Context(), usecase.ExternalTaskExecutionEvent{
			EventID:   request.EventID,
			RunID:     request.RunID,
			ThreadID:  request.ThreadID,
			EventType: request.EventType,
			Source:    request.Source,
			Sequence:  request.Sequence,
			Timestamp: request.Timestamp,
			Payload:   request.Payload,
		})
		if err != nil {
			http.Error(w, fmt.Sprintf("reject execution event: %v", err), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_ = json.NewEncoder(w).Encode(map[string]any{"event_id": stored.EventID, "sequence": stored.Sequence})
	}
}

func executionRunIDFromPath(path string) (string, bool) {
	trimmed := strings.Trim(strings.TrimPrefix(path, executionEventsPathPrefix), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] != "events" {
		return "", false
	}
	return parts[0], true
}

func bearerToken(header string) string {
	parts := strings.Fields(header)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") {
		return ""
	}
	return parts[1]
}
