package v1

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/execution"
)

type SSEDeps struct {
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string
	Authorize     func(r *http.Request, userID, taskID string) bool
	Feed          usecase.ExecutionEventFeed

	AuthzDeniedCode string
}

func NewSSEHandler(deps SSEDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		taskIDs := resolveWorkflowIDs(r)
		if len(taskIDs) == 0 {
			http.Error(w, "workflow_id required", http.StatusBadRequest)
			return
		}
		userID := deps.UserID(r)
		for _, taskID := range taskIDs {
			if !deps.Authorize(r, userID, taskID) {
				deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for workflow stream", map[string]any{"workflow_id": taskID})
				return
			}
		}
		if deps.Feed == nil {
			http.Error(w, "execution event feed unavailable", http.StatusServiceUnavailable)
			return
		}

		cursor := executionEventCursor(r, taskIDs)
		subscriptions := make([]usecase.TaskExecutionSubscription, 0, len(taskIDs))
		for _, taskID := range taskIDs {
			subscription, err := deps.Feed.Subscribe(r.Context(), taskID, cursor[taskID])
			if err != nil {
				for _, opened := range subscriptions {
					_ = opened.Close()
				}
				http.Error(w, "failed to subscribe to execution events", http.StatusBadGateway)
				return
			}
			subscriptions = append(subscriptions, subscription)
		}
		defer func() {
			for _, subscription := range subscriptions {
				_ = subscription.Close()
			}
		}()

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache, no-transform")
		w.Header().Set("Connection", "keep-alive")
		w.Header().Set("X-Accel-Buffering", "no")
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming unsupported", http.StatusInternalServerError)
			return
		}

		fmt.Fprint(w, ": connected\n\n")
		flusher.Flush()
		streamExecutionEvents(r.Context(), subscriptions, func(event usecase.TaskExecutionEvent) {
			payload, err := json.Marshal(executionEventPayload(event))
			if err != nil {
				return
			}
			fmt.Fprintf(w, "id: %d\n", event.Sequence)
			fmt.Fprintf(w, "event: %s\n", execution.KardcraftEventType(event.EventType))
			fmt.Fprintf(w, "data: %s\n\n", payload)
			flusher.Flush()
		}, func() {
			fmt.Fprintf(w, ": ping %d\n\n", time.Now().UTC().Unix())
			flusher.Flush()
		})
	}
}

func streamExecutionEvents(ctx context.Context, subscriptions []usecase.TaskExecutionSubscription, emit func(usecase.TaskExecutionEvent), heartbeat func()) {
	merged := make(chan usecase.TaskExecutionEvent)
	var group sync.WaitGroup
	for _, subscription := range subscriptions {
		group.Add(1)
		go func(subscription usecase.TaskExecutionSubscription) {
			defer group.Done()
			for event := range subscription.Events() {
				select {
				case merged <- event:
				case <-ctx.Done():
					return
				}
			}
		}(subscription)
	}
	go func() {
		group.Wait()
		close(merged)
	}()

	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			heartbeat()
		case event, ok := <-merged:
			if !ok {
				return
			}
			emit(event)
		}
	}
}

func executionEventPayload(event usecase.TaskExecutionEvent) map[string]any {
	payload := make(map[string]any, len(event.Payload)+10)
	for key, value := range event.Payload {
		payload[key] = value
	}
	payload["event_id"] = event.EventID
	kardcraftType := execution.KardcraftEventType(event.EventType)
	payload["event_type"] = kardcraftType
	payload["workflow_id"] = event.RunID
	payload["session_id"] = event.ThreadID
	payload["run_id"] = event.RunID
	payload["thread_id"] = event.ThreadID
	payload["sequence"] = event.Sequence
	payload["occurred_at"] = event.Timestamp.UTC().Format(time.RFC3339Nano)
	payload["schema_version"] = 1

	correlationID, _ := event.Payload["correlation_id"].(string)
	if correlationID == "" {
		correlationID = event.RunID
	}
	payload["correlation_id"] = correlationID
	return payload
}

func resolveWorkflowIDs(r *http.Request) []string {
	values := r.URL.Query()["workflow_id"]
	seen := make(map[string]struct{}, len(values))
	var taskIDs []string
	for _, value := range values {
		for _, token := range strings.Split(value, ",") {
			taskID := strings.TrimSpace(token)
			if taskID == "" {
				continue
			}
			if _, exists := seen[taskID]; exists {
				continue
			}
			seen[taskID] = struct{}{}
			taskIDs = append(taskIDs, taskID)
		}
	}
	return taskIDs
}

func executionEventCursor(r *http.Request, taskIDs []string) map[string]int64 {
	cursor := make(map[string]int64, len(taskIDs))
	if len(taskIDs) != 1 {
		return cursor
	}
	value := strings.TrimSpace(r.URL.Query().Get("last_event_id"))
	if value == "" {
		value = strings.TrimSpace(r.Header.Get("Last-Event-ID"))
	}
	if sequence, err := strconv.ParseInt(value, 10, 64); err == nil && sequence >= 0 {
		cursor[taskIDs[0]] = sequence
	}
	return cursor
}
