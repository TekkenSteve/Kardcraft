package v1

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/outcomeprojector"
)

type AgentOSEventsDeps struct {
	WriteJSON      func(w http.ResponseWriter, status int, v any)
	WriteAPIError  func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	ReadModel      usecase.ReadModel
	OutcomeStore   outcomeprojector.Store
	AppendTimeline func(workflowID, sessionID, eventType, message, streamID string, payload any, persist bool)
}

type AgentOSEventInput struct {
	EventID   string            `json:"event_id"`
	RunID     string            `json:"run_id"`
	ThreadID  string            `json:"thread_id,omitempty"`
	Sequence  int64             `json:"sequence,omitempty"`
	EventType string            `json:"event_type"`
	Source    string            `json:"source"`
	Timestamp time.Time         `json:"timestamp"`
	TraceID   string            `json:"trace_id,omitempty"`
	Tags      map[string]string `json:"tags,omitempty"`
	Payload   map[string]any    `json:"payload,omitempty"`
}

func NewAgentOSEventsHandler(deps AgentOSEventsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		runID := agentOSRunIDFromPath(r.URL.Path)
		if runID == "" {
			http.NotFound(w, r)
			return
		}
		var ev AgentOSEventInput
		if err := json.NewDecoder(r.Body).Decode(&ev); err != nil {
			http.Error(w, "invalid event body", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(ev.RunID) == "" {
			ev.RunID = runID
		}
		if ev.RunID != runID {
			http.Error(w, "run_id in path and body must match", http.StatusBadRequest)
			return
		}
		if ev.Timestamp.IsZero() {
			ev.Timestamp = time.Now().UTC()
		}
		if ev.Payload == nil {
			ev.Payload = map[string]any{}
		}
		eventType := strings.TrimSpace(ev.EventType)
		if eventType == "" {
			eventType = usecase.EventWorkflowProgress
		}
		eventType = kardcraftEventTypeFromAgentOS(eventType)
		taskID := firstNonEmptyStringAny(ev.Payload["task_id"], ev.RunID)
		workflowID := firstNonEmptyStringAny(ev.Payload["workflow_id"], taskID)
		sessionID := firstNonEmptyStringAny(ev.Payload["session_id"], ev.ThreadID)
		if sessionID == "" && deps.ReadModel != nil {
			if resolved, err := deps.ReadModel.GetTaskSession(r.Context(), taskID); err == nil {
				sessionID = strings.TrimSpace(resolved)
			}
		}
		message := firstNonEmptyStringAny(ev.Payload["message"])
		streamID := agentOSEventStreamID(ev)

		payload := normalizedAgentOSEventPayload(ev, taskID, workflowID, sessionID, eventType)
		outcomePayload, hasOutcome := taskOutcomeFromAgentOSEvent(eventType, payload)
		if hasOutcome && deps.OutcomeStore != nil {
			projection, err := outcomeprojector.New(deps.OutcomeStore).ProjectWithEvents(r.Context(), outcomeprojector.Input{
				TaskID:        taskID,
				WorkflowID:    workflowID,
				RunID:         ev.RunID,
				Status:        outcomeStatusFromEvent(eventType, outcomePayload),
				Result:        outcomePayload,
				Error:         firstNonEmptyStringAny(payload["error"]),
				CompletedAt:   ev.Timestamp,
				CorrelationID: firstNonEmptyStringAny(payload["correlation_id"]),
				TerminalNote:  message,
			})
			if err != nil {
				deps.WriteAPIError(w, http.StatusInternalServerError, "agentos_event_projection_failed", err.Error(), map[string]any{"run_id": ev.RunID, "task_id": taskID})
				return
			}
			for _, projected := range projection.Events {
				deps.AppendTimeline(
					projected.WorkflowID,
					projected.SessionID,
					projected.EventType,
					projected.Message,
					projected.StreamID,
					projected.Payload,
					false,
				)
			}
		} else {
			if status, ok := taskStatusFromAgentOSEvent(eventType); ok && deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(r.Context(), taskID, status, firstNonEmptyStringAny(payload["error"]))
			}
			projectAgentOSUsage(r.Context(), deps.ReadModel, workflowID, sessionID, taskID, streamID, eventType, payload)
			deps.AppendTimeline(workflowID, sessionID, eventType, message, streamID, payload, true)
		}

		deps.WriteJSON(w, http.StatusAccepted, map[string]any{
			"run_id":    ev.RunID,
			"event_id":  streamID,
			"projected": true,
		})
	}
}

func projectAgentOSUsage(ctx context.Context, readModel usecase.ReadModel, workflowID, sessionID, taskID, streamID, eventType string, payload map[string]any) {
	if readModel == nil {
		return
	}
	NewUsageProjector(
		readModel.InsertLLMUsage,
		nil,
		nil,
		nil,
		nil,
		nil,
	).Project(ctx, NormalizedEvent{
		WorkflowID: workflowID,
		SessionID:  sessionID,
		TaskID:     taskID,
		EventType:  eventType,
		StreamID:   streamID,
		Payload:    payload,
	})
}

func taskStatusFromAgentOSEvent(eventType string) (string, bool) {
	switch strings.ToUpper(strings.TrimSpace(eventType)) {
	case usecase.EventWorkflowStarted, usecase.EventWorkflowWaitingInput, usecase.EventMessageReceived, usecase.EventWorkflowResumed, usecase.EventWorkflowProgress:
		return "running", true
	case usecase.EventWorkflowPaused:
		return "paused", true
	case usecase.EventWorkflowCompleted:
		return "completed", true
	case usecase.EventWorkflowFailed:
		return "failed", true
	case usecase.EventWorkflowCancelled:
		return "cancelled", true
	default:
		return "", false
	}
}

func agentOSRunIDFromPath(path string) string {
	trimmed := strings.Trim(strings.TrimPrefix(path, "/api/v1/agentos/runs/"), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) != 2 || parts[1] != "events" {
		return ""
	}
	return strings.TrimSpace(parts[0])
}

func agentOSEventStreamID(ev AgentOSEventInput) string {
	if strings.TrimSpace(ev.EventID) != "" {
		return "agentos:" + strings.TrimSpace(ev.EventID)
	}
	if ev.Sequence > 0 {
		return fmt.Sprintf("agentos:%s:%d", strings.TrimSpace(ev.RunID), ev.Sequence)
	}
	return fmt.Sprintf("agentos:%s:%d", strings.TrimSpace(ev.RunID), ev.Timestamp.UnixNano())
}

func normalizedAgentOSEventPayload(ev AgentOSEventInput, taskID, workflowID, sessionID, eventType string) map[string]any {
	payload := map[string]any{}
	for key, value := range ev.Payload {
		payload[key] = value
	}
	payload["event_type"] = eventType
	payload["run_id"] = ev.RunID
	payload["thread_id"] = ev.ThreadID
	payload["task_id"] = taskID
	payload["workflow_id"] = workflowID
	payload["session_id"] = sessionID
	payload["source"] = ev.Source
	payload["timestamp"] = ev.Timestamp.UTC().Format(time.RFC3339Nano)
	if ev.EventID != "" {
		payload["agentos_event_id"] = ev.EventID
	}
	if ev.TraceID != "" {
		payload["trace_id"] = ev.TraceID
	}
	if len(ev.Tags) > 0 {
		payload["tags"] = ev.Tags
	}
	return payload
}

func taskOutcomeFromAgentOSEvent(eventType string, payload map[string]any) (map[string]any, bool) {
	if outcome, ok := payload["task_outcome"].(map[string]any); ok && len(outcome) > 0 {
		return outcome, isTerminalAgentOSEvent(eventType)
	}
	if strings.EqualFold(firstNonEmptyStringAny(payload["schema_version"]), "task-outcome") && isTerminalAgentOSEvent(eventType) {
		return payload, true
	}
	return nil, false
}

func isTerminalAgentOSEvent(eventType string) bool {
	switch strings.ToUpper(strings.TrimSpace(eventType)) {
	case usecase.EventWorkflowCompleted, usecase.EventWorkflowFailed, usecase.EventWorkflowCancelled:
		return true
	default:
		return false
	}
}

func outcomeStatusFromEvent(eventType string, outcome map[string]any) string {
	switch strings.ToLower(strings.TrimSpace(firstNonEmptyStringAny(outcome["status"]))) {
	case "completed", "success", "succeeded":
		return "completed"
	case "failed", "error":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	}
	switch strings.ToUpper(strings.TrimSpace(eventType)) {
	case usecase.EventWorkflowFailed:
		return "failed"
	case usecase.EventWorkflowCancelled:
		return "cancelled"
	default:
		return "completed"
	}
}
