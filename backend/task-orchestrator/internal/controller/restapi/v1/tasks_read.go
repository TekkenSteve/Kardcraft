package v1

import (
	"context"
	"crypto/rand"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

func handleListTasks(w http.ResponseWriter, r *http.Request, deps TasksDeps) {
	limit := 50
	offset := 0
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil {
			limit = n
		}
	}
	if raw := r.URL.Query().Get("offset"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil {
			offset = n
		}
	}
	userID := deps.UserID(r)
	items, total, err := deps.TaskService.ListTasks(r.Context(), usecase.ListTasksInput{UserID: userID, Limit: limit, Offset: offset})
	if err != nil {
		http.Error(w, "failed to list tasks", http.StatusInternalServerError)
		return
	}
	taskIDs := make([]string, 0, len(items))
	for _, t := range items {
		taskIDs = append(taskIDs, t.ID().String())
	}
	usageByTask := map[string]usecase.TaskUsageSummary{}
	if deps.ReadModel != nil && len(taskIDs) > 0 {
		usageByTask, err = deps.ReadModel.GetTaskUsageSummaryMapByTaskIDs(r.Context(), userID, taskIDs)
		if err != nil {
			http.Error(w, "failed to load usage summary", http.StatusInternalServerError)
			return
		}
	}
	tasks := make([]map[string]any, 0, len(items))
	for _, t := range items {
		usage := usageByTask[t.ID().String()]
		entry := map[string]any{
			"task_id":     t.ID().String(),
			"workflow_id": t.ID().String(),
			"query":       t.Query(),
			"status":      MapTaskStatus(t),
			"mode":        t.TaskType(),
			"created_at":  t.CreatedAt().UTC().Format(time.RFC3339),
			"total_token_usage": map[string]any{
				"total_tokens":      usage.TotalTokens,
				"cost_usd":          usage.TotalCostUSD,
				"prompt_tokens":     usage.PromptTokens,
				"completion_tokens": usage.CompletionTokens,
			},
		}
		if done := t.CompletedAt(); done != nil {
			entry["completed_at"] = done.UTC().Format(time.RFC3339)
		}
		tasks = append(tasks, entry)
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"tasks": tasks, "total_count": total})
}

func handleGetTask(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	userID := deps.UserID(r)
	if !deps.AuthorizeTaskAccess(r, userID, taskID) {
		deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for task resource", map[string]any{"task_id": taskID})
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.AgentRuntime == nil {
		http.Error(w, "agent runtime unavailable", http.StatusServiceUnavailable)
		return
	}
	task, err := deps.ReadModel.GetTask(r.Context(), taskID, userID)
	if err != nil {
		http.Error(w, "task not found", http.StatusNotFound)
		return
	}
	status, err := deps.AgentRuntime.GetAgentRunStatus(r.Context(), taskID)
	if err != nil {
		http.Error(w, "failed to retrieve agent run status", http.StatusBadGateway)
		return
	}
	sessionID := ""
	if sid, err := deps.ReadModel.GetTaskSession(r.Context(), taskID); err == nil {
		sessionID = sid
	}
	response := map[string]any{
		"workflow_id": task.WorkflowID,
		"run_id":      firstNonEmptyString(status.RunID, taskID),
		"task_id":     taskID,
		"task_type":   valueFromPtr(task.TaskType),
		"query":       valueFromPtr(task.Query),
		"status":      taskStatusFromAgentLifecycle(status.LifecycleState, valueFromPtr(task.Status)),
		"session_id":  sessionID,
		"metadata": map[string]any{
			"task_context": map[string]any{},
		},
	}
	if task.StartedAt != nil {
		response["created_at"] = task.StartedAt.UTC().Format(time.RFC3339)
	}
	if task.CompletedAt != nil {
		response["finished_at"] = task.CompletedAt.UTC().Format(time.RFC3339)
	}
	if task.Result != nil {
		response["result"] = task.Result
		response["final_output"] = task.Result
	}
	if task.Error != nil {
		response["error_message"] = *task.Error
	}
	if task.DurationMS != nil {
		response["duration_ms"] = *task.DurationMS
	}
	deps.WriteJSON(w, http.StatusOK, response)
}

func taskStatusFromAgentLifecycle(lifecycle, persisted string) string {
	switch strings.ToLower(strings.TrimSpace(lifecycle)) {
	case "completed", "succeeded":
		return "completed"
	case "failed":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	case "queued", "created", "pending":
		return "queued"
	case "running", "paused":
		return "running"
	}
	switch strings.ToLower(strings.TrimSpace(persisted)) {
	case "completed", "failed", "cancelled", "queued", "running":
		return strings.ToLower(strings.TrimSpace(persisted))
	default:
		return "queued"
	}
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func handleTaskControl(w http.ResponseWriter, r *http.Request, taskID string, action string, deps TasksDeps) {
	userID := deps.UserID(r)
	if !deps.AuthorizeTaskAccess(r, userID, taskID) {
		deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for task resource", map[string]any{"task_id": taskID})
		return
	}
	if action == "planner-trace" {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleTaskPlannerTrace(w, r, taskID, deps)
		return
	}
	if action == "control-state" {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleTaskControlState(w, r, taskID, deps)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	idempotencyKey := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if idempotencyKey == "" {
		deps.WriteAPIError(w, http.StatusBadRequest, deps.IdempotencyRequiredCode, "Idempotency-Key header is required", map[string]any{"task_id": taskID, "action": action})
		return
	}
	var req struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&req)
	if deps.CommandService == nil {
		http.Error(w, "command service unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.AgentRuntime == nil {
		http.Error(w, "agent runtime unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	sessionID, err := deps.ReadModel.GetTaskSession(r.Context(), taskID)
	if err != nil {
		deps.WriteJSON(w, http.StatusBadRequest, map[string]any{"success": false, "message": err.Error(), "workflow_id": taskID})
		return
	}
	_, err = deps.CommandService.ControlSession(r.Context(), usecase.SessionControlCommand{
		SessionID:      sessionID,
		TaskID:         taskID,
		UserID:         userID,
		Action:         action,
		Reason:         req.Reason,
		IdempotencyKey: idempotencyKey,
	})
	if errors.Is(err, usecase.ErrInvalidTransition) {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err != nil {
		deps.WriteJSON(w, http.StatusBadRequest, map[string]any{"success": false, "message": err.Error(), "workflow_id": taskID})
		return
	}
	appendControlTimelineEvent(r.Context(), taskID, action, req.Reason, userID, idempotencyKey, deps)
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"success":     true,
		"message":     fmt.Sprintf("Task %s signal sent successfully", action),
		"workflow_id": taskID,
	})
}

func appendControlTimelineEvent(ctx context.Context, taskID, action, reason, requestedBy, idempotencyKey string, deps TasksDeps) {
	if deps.AppendTimelineWithStreamID == nil {
		return
	}
	eventType, message := controlTimelineEvent(action, reason)
	if eventType == "" {
		return
	}
	sessionID := ""
	if deps.ReadModel != nil {
		if resolved, err := deps.ReadModel.GetTaskSession(ctx, taskID); err == nil {
			sessionID = strings.TrimSpace(resolved)
		}
	}
	runID := ""
	if deps.AgentRuntime != nil {
		if status, err := deps.AgentRuntime.GetAgentRunStatus(ctx, taskID); err == nil {
			runID = strings.TrimSpace(status.RunID)
		}
	}
	streamID := deterministicControlStreamID(taskID, action, idempotencyKey)
	deps.AppendTimelineWithStreamID(taskID, sessionID, eventType, message, streamID, map[string]any{
		"task_id":          taskID,
		"workflow_id":      taskID,
		"run_id":           runID,
		"correlation_id":   strings.TrimSpace(idempotencyKey),
		"action":           strings.ToLower(strings.TrimSpace(action)),
		"reason":           strings.TrimSpace(reason),
		"requested_by":     strings.TrimSpace(requestedBy),
		"idempotency_key":  strings.TrimSpace(idempotencyKey),
		"schema_version":   "task-control-event.v1",
		"control_event_id": streamID,
	})
}

func controlTimelineEvent(action, reason string) (string, string) {
	normalizedAction := strings.ToLower(strings.TrimSpace(action))
	normalizedReason := strings.TrimSpace(reason)
	switch normalizedAction {
	case "pause":
		if normalizedReason == "" {
			normalizedReason = "Task paused"
		}
		return usecase.EventWorkflowPaused, normalizedReason
	case "resume":
		if normalizedReason == "" {
			normalizedReason = "Task resumed"
		}
		return usecase.EventWorkflowResumed, normalizedReason
	case "cancel":
		if normalizedReason == "" {
			normalizedReason = "Task cancelled"
		}
		return usecase.EventWorkflowCancelled, normalizedReason
	default:
		return "", ""
	}
}

func deterministicControlStreamID(taskID, action, idempotencyKey string) string {
	sum := sha1.Sum([]byte(strings.Join([]string{
		"task-control",
		strings.TrimSpace(taskID),
		strings.ToLower(strings.TrimSpace(action)),
		strings.TrimSpace(idempotencyKey),
	}, "|")))
	return "task_control:" + hex.EncodeToString(sum[:])
}

func ensureCorrelationID(value string) (string, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed != "" {
		return trimmed, nil
	}
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

func handleTaskPlannerTrace(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	events, err := deps.ReadModel.ListWorkflowEvents(r.Context(), taskID, 2000, 0)
	if err != nil {
		http.Error(w, "failed to load planner trace", http.StatusInternalServerError)
		return
	}
	records := make([]map[string]any, 0)
	for _, ev := range events {
		if !strings.EqualFold(strings.TrimSpace(ev.Type), "PLANNER_TRACE") {
			continue
		}
		item := map[string]any{
			"event_id":    ev.ID,
			"event_type":  ev.Type,
			"timestamp":   ev.Timestamp.UTC().Format(time.RFC3339),
			"message":     strings.TrimSpace(valueFromPtr(ev.Message)),
			"trace":       nil,
			"raw_payload": nil,
		}
		payload := parsePayloadText(ev.Payload)
		if parsed, ok := payload.(map[string]any); ok {
			item["trace"] = parsed
		} else {
			item["raw_payload"] = payload
		}
		if ev.StreamID != nil {
			item["stream_id"] = *ev.StreamID
		}
		records = append(records, item)
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"task_id":       taskID,
		"planner_trace": records,
		"total_count":   len(records),
	})
}

func handleTaskControlState(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	if deps.AgentRuntime == nil {
		http.Error(w, "agent runtime unavailable", http.StatusServiceUnavailable)
		return
	}
	status, err := deps.AgentRuntime.GetAgentRunStatus(r.Context(), taskID)
	if err != nil {
		http.Error(w, "failed to retrieve agent run status", http.StatusBadGateway)
		return
	}
	lifecycle := strings.ToLower(strings.TrimSpace(status.LifecycleState))
	isPaused := lifecycle == "paused"
	isCancelled := lifecycle == "cancelled" || lifecycle == "canceled"
	pausedAt := ""
	if isPaused && !status.UpdatedAt.IsZero() {
		pausedAt = status.UpdatedAt.UTC().Format(time.RFC3339)
	}
	pauseReason := ""
	cancelReason := ""
	if isPaused {
		pauseReason = status.Reason
	}
	if isCancelled {
		cancelReason = status.Reason
	}
	userID := deps.UserID(r)
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"is_paused":     isPaused,
		"is_cancelled":  isCancelled,
		"paused_at":     pausedAt,
		"pause_reason":  pauseReason,
		"paused_by":     userID,
		"cancel_reason": cancelReason,
		"cancelled_by":  userID,
	})
}
