package httpserver

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"task-orchestrator/internal/infrastructure/persistence"
	"task-orchestrator/internal/infrastructure/temporal/workflows"
)

func (s *Server) sessionsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	limit := 20
	offset := 0
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			limit = n
		}
	}
	if raw := r.URL.Query().Get("offset"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n >= 0 {
			offset = n
		}
	}
	list, total, err := s.sessionDB.ListSessions(r.Context(), userID, limit, offset)
	if err != nil {
		http.Error(w, "failed to list sessions", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"sessions": list, "total_count": total})
}

func (s *Server) sessionsRouter(w http.ResponseWriter, r *http.Request) {
	trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/sessions/"), "/")
	if trimmed == "" {
		http.NotFound(w, r)
		return
	}
	parts := strings.Split(trimmed, "/")
	sessionID := parts[0]
	if len(parts) == 1 {
		s.handleSessionDetail(w, r, sessionID)
		return
	}
	suffix := parts[1]
	switch suffix {
	case "conversation":
		s.handleSessionConversation(w, r, sessionID)
	case "timeline":
		s.handleSessionTimeline(w, r, sessionID)
	case "history":
		s.handleSessionHistory(w, r, sessionID)
	case "workspace":
		s.handleSessionWorkspace(w, r, sessionID)
	case "state":
		s.handleSessionState(w, r, sessionID)
	case "pause", "resume", "cancel":
		s.handleSessionControl(w, r, sessionID, suffix)
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) handleSessionDetail(w http.ResponseWriter, r *http.Request, sessionID string) {
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	switch r.Method {
	case http.MethodGet:
		rec, err := s.sessionDB.GetSession(r.Context(), sessionID, userID)
		if err != nil || rec == nil {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}
		writeJSON(w, http.StatusOK, rec)
	case http.MethodPatch:
		var req struct {
			Title  *string `json:"title"`
			Pinned *bool   `json:"pinned"`
		}
		if err := parseJSON(r, &req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if req.Title == nil && req.Pinned == nil {
			http.Error(w, "no fields to update", http.StatusBadRequest)
			return
		}
		if err := s.sessionDB.UpdateSessionMeta(r.Context(), sessionID, userID, req.Title, req.Pinned); err != nil {
			http.Error(w, "failed to update session", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	case http.MethodDelete:
		affected, err := s.sessionDB.DeleteSession(r.Context(), sessionID, userID)
		if err != nil {
			http.Error(w, "failed to delete session", http.StatusInternalServerError)
			return
		}
		if affected == 0 {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func extractAssistantContentFromEvents(events []persistence.EventRow) (string, time.Time) {
	for i := len(events) - 1; i >= 0; i-- {
		ev := events[i]
		msg := ""
		if ev.Message != nil {
			msg = strings.TrimSpace(*ev.Message)
		}
		if msg != "" && (ev.Type == "WORKFLOW_COMPLETED" || ev.Type == "thread.message.completed" || ev.Type == "LLM_OUTPUT") {
			return msg, ev.Timestamp
		}
	}
	return "", time.Time{}
}

func extractResultMessage(result any) string {
	if result == nil {
		return ""
	}
	switch v := result.(type) {
	case string:
		text := strings.TrimSpace(v)
		if text == "" {
			return ""
		}
		var parsed any
		if err := json.Unmarshal([]byte(text), &parsed); err == nil {
			if msg := extractResultMessage(parsed); msg != "" {
				return msg
			}
		}
		return text
	case []byte:
		return extractResultMessage(string(v))
	case map[string]any:
		if out, err := workflows.DecodeTaskOutcome(v); err == nil {
			if msg := strings.TrimSpace(out.Message); msg != "" {
				return msg
			}
		}
		// Handle wrapped outcome payloads produced by activity/temporal envelopes.
		for _, nestedKey := range []string{"result", "data"} {
			if nested, ok := v[nestedKey]; ok {
				if msg := extractResultMessage(nested); msg != "" {
					return msg
				}
			}
		}
		if !sessionReadFallbackEnabled() {
			return ""
		}
		for _, key := range []string{"message", "response", "content", "text", "output", "result"} {
			if val, ok := v[key]; ok {
				if s, ok := val.(string); ok && strings.TrimSpace(s) != "" {
					return strings.TrimSpace(s)
				}
			}
		}
	case []any:
		for _, item := range v {
			if msg := extractResultMessage(item); msg != "" {
				return msg
			}
		}
	}
	return ""
}

func sessionReadFallbackEnabled() bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("TASK_READ_PATH_BACKFILL_ENABLED")), "true")
}

func (s *Server) handleSessionConversation(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	if _, err := s.sessionDB.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := s.sessionDB.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session history", http.StatusInternalServerError)
		return
	}
	events, err := s.sessionDB.ListSessionEvents(r.Context(), sessionID, 2000, 0)
	if err != nil {
		http.Error(w, "failed to load session events", http.StatusInternalServerError)
		return
	}
	eventsByTask := make(map[string][]persistence.EventRow)
	for _, ev := range events {
		taskID := ""
		if ev.TaskID != nil {
			taskID = *ev.TaskID
		}
		eventsByTask[taskID] = append(eventsByTask[taskID], ev)
	}
	messages := make([]map[string]any, 0)
	for _, t := range tasks {
		taskID := t.TaskID
		timestamp := ""
		if t.StartedAt != nil {
			timestamp = t.StartedAt.UTC().Format(time.RFC3339)
		} else if t.CompletedAt != nil {
			timestamp = t.CompletedAt.UTC().Format(time.RFC3339)
		}
		messages = append(messages, map[string]any{
			"id":        fmt.Sprintf("user-%s", taskID),
			"role":      "user",
			"content":   valueFromPtr(t.Query),
			"timestamp": timestamp,
			"task_id":   taskID,
		})
		assistantContent := extractResultMessage(t.Result)
		if assistantContent == "" {
			if text, ts := extractAssistantContentFromEvents(eventsByTask[taskID]); text != "" {
				assistantContent = text
				if !ts.IsZero() {
					timestamp = ts.UTC().Format(time.RFC3339)
				}
			}
		}
		if assistantContent != "" {
			messages = append(messages, map[string]any{
				"id":        fmt.Sprintf("assistant-%s", taskID),
				"role":      "assistant",
				"content":   assistantContent,
				"timestamp": timestamp,
				"task_id":   taskID,
			})
		} else if strings.EqualFold(valueFromPtr(t.Status), "cancelled") {
			messages = append(messages, map[string]any{
				"id":        fmt.Sprintf("assistant-%s", taskID),
				"role":      "assistant",
				"content":   "This task was cancelled.",
				"timestamp": timestamp,
				"task_id":   taskID,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "messages": messages})
}

func (s *Server) handleSessionTimeline(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	if _, err := s.sessionDB.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	limit := 500
	offset := 0
	includePayload := true
	if raw := strings.TrimSpace(r.URL.Query().Get("include_payload")); raw != "" {
		includePayload = strings.EqualFold(raw, "true")
	}
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

	events, err := s.sessionDB.ListSessionEvents(r.Context(), sessionID, limit, offset)
	if err != nil {
		http.Error(w, "failed to load session events", http.StatusInternalServerError)
		return
	}
	selected := make([]TimelineEvent, 0, len(events))
	for _, ev := range events {
		item := TimelineEvent{
			ID:        ev.ID,
			Type:      ev.Type,
			Timestamp: ev.Timestamp.UTC().Format(time.RFC3339),
		}
		if ev.Message != nil {
			item.Message = *ev.Message
		}
		if ev.Workflow != nil {
			item.WorkflowID = *ev.Workflow
		}
		if ev.TaskID != nil {
			item.TaskID = *ev.TaskID
		}
		if ev.StreamID != nil {
			item.StreamID = *ev.StreamID
		}
		if includePayload {
			item.Payload = parsePayloadText(ev.Payload)
		}
		selected = append(selected, item)
	}
	projectionStatus := "empty"
	if len(selected) > 0 {
		projectionStatus = "hydrated"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"session_id":        sessionID,
		"events":            selected,
		"projection_status": projectionStatus,
	})
}

func (s *Server) handleSessionHistory(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	if _, err := s.sessionDB.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := s.sessionDB.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session history", http.StatusInternalServerError)
		return
	}
	usageByTask, err := s.sessionDB.GetTaskUsageSummaryMapBySession(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load usage summary", http.StatusInternalServerError)
		return
	}
	items := make([]map[string]any, 0, len(tasks))
	for _, t := range tasks {
		usage := usageByTask[t.TaskID]
		item := map[string]any{
			"task_id":        t.TaskID,
			"workflow_id":    t.WorkflowID,
			"query":          valueFromPtr(t.Query),
			"status":         valueFromPtr(t.Status),
			"mode":           valueFromPtr(t.TaskType),
			"total_tokens":   usage.TotalTokens,
			"total_cost_usd": usage.TotalCostUSD,
		}
		if len(usage.ModelBreakdown) > 0 {
			modelBreakdown := make([]map[string]any, 0, len(usage.ModelBreakdown))
			totalExecutions := 0
			estimatedExecutions := 0
			for _, entry := range usage.ModelBreakdown {
				totalExecutions += entry.Executions
				estimatedExecutions += entry.EstimatedExecutions
				modelBreakdown = append(modelBreakdown, map[string]any{
					"model":                entry.Model,
					"provider":             entry.Provider,
					"executions":           entry.Executions,
					"tokens":               entry.Tokens,
					"cost_usd":             entry.CostUSD,
					"prompt_tokens":        entry.PromptTokens,
					"completion_tokens":    entry.CompletionTokens,
					"cache_read_tokens":    entry.CacheReadTokens,
					"cache_write_tokens":   entry.CacheWriteTokens,
					"estimated_executions": entry.EstimatedExecutions,
				})
			}
			estimatedRatio := 0.0
			if totalExecutions > 0 {
				estimatedRatio = float64(estimatedExecutions) / float64(totalExecutions)
			}
			item["metadata"] = map[string]any{
				"model_breakdown": modelBreakdown,
				"usage_quality": map[string]any{
					"has_estimated_usage": estimatedExecutions > 0,
					"estimated_ratio":     estimatedRatio,
				},
			}
			item["model_used"] = usage.ModelBreakdown[0].Model
			item["provider"] = usage.ModelBreakdown[0].Provider
		}
		if t.StartedAt != nil {
			item["started_at"] = t.StartedAt.UTC().Format(time.RFC3339)
		}
		if t.CompletedAt != nil {
			item["completed_at"] = t.CompletedAt.UTC().Format(time.RFC3339)
			if t.DurationMS != nil {
				item["duration_ms"] = *t.DurationMS
			}
		}
		if t.Error != nil {
			item["error_message"] = *t.Error
		}
		items = append(items, item)
	}
	writeJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "tasks": items})
}

func (s *Server) handleSessionWorkspace(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	if _, err := s.sessionDB.GetSession(r.Context(), sessionID, userID); err != nil {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for session resource", map[string]any{
			"session_id": sessionID,
		})
		return
	}
	resp, err := s.sessionDB.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, normalizeWorkspaceResponse(resp, sessionID))
}

func isTaskActiveStatus(raw string) bool {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "pending", "queued", "running", "paused":
		return true
	default:
		return false
	}
}

func normalizeTaskStateForControl(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "pending", "queued", "running":
		return "RUNNING"
	case "paused":
		return "PAUSED"
	case "cancelled", "canceled":
		return "CANCELED"
	case "completed", "success":
		return "SUCCEEDED"
	case "failed", "error":
		return "FAILED"
	default:
		return "IDLE"
	}
}

func controlStateFromTaskState(taskState string) string {
	switch taskState {
	case "RUNNING":
		return "ACTIVE_RUNNING"
	case "PAUSED":
		return "ACTIVE_PAUSED"
	case "CANCELED", "SUCCEEDED", "FAILED":
		return "IDLE"
	default:
		return "IDLE"
	}
}

func resolveSessionActiveTask(tasks []persistence.TaskRow) (persistence.TaskRow, bool) {
	for i := len(tasks) - 1; i >= 0; i-- {
		status := valueFromPtr(tasks[i].Status)
		if isTaskActiveStatus(status) {
			return tasks[i], true
		}
	}
	return persistence.TaskRow{}, false
}

func (s *Server) handleSessionControl(w http.ResponseWriter, r *http.Request, sessionID string, action string) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if strings.TrimSpace(r.Header.Get("Idempotency-Key")) == "" {
		writeAPIError(w, http.StatusBadRequest, errCodeIdempotencyKeyRequired, "Idempotency-Key header is required", nil)
		return
	}
	if !s.isTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}

	userID := userIDFromContext(r.Context())
	if _, err := s.sessionDB.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := s.sessionDB.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session tasks", http.StatusInternalServerError)
		return
	}
	activeTask, ok := resolveSessionActiveTask(tasks)
	if !ok {
		writeAPIError(w, http.StatusNotFound, errCodeNoActiveTask, "session has no active task", map[string]any{
			"session_id": sessionID,
		})
		return
	}
	taskID := activeTask.TaskID
	currentTaskState := normalizeTaskStateForControl(valueFromPtr(activeTask.Status))
	switch action {
	case "pause":
		if currentTaskState != "RUNNING" {
			writeAPIError(w, http.StatusConflict, errCodeInvalidTransition, "active task is not running", map[string]any{
				"session_id": sessionID,
				"task_id":    taskID,
				"task_state": currentTaskState,
			})
			return
		}
	case "resume":
		if currentTaskState != "PAUSED" {
			writeAPIError(w, http.StatusConflict, errCodeInvalidTransition, "active task is not paused", map[string]any{
				"session_id": sessionID,
				"task_id":    taskID,
				"task_state": currentTaskState,
			})
			return
		}
	case "cancel":
		if currentTaskState != "RUNNING" && currentTaskState != "PAUSED" {
			writeAPIError(w, http.StatusConflict, errCodeInvalidTransition, "active task is not cancellable", map[string]any{
				"session_id": sessionID,
				"task_id":    taskID,
				"task_state": currentTaskState,
			})
			return
		}
	default:
		http.Error(w, "unsupported action", http.StatusBadRequest)
		return
	}

	var req struct {
		Reason string `json:"reason"`
	}
	_ = parseJSON(r, &req)
	signalPayload := map[string]any{
		"reason":     req.Reason,
		"request_by": userID,
		"timestamp":  time.Now().UTC(),
	}

	switch action {
	case "pause":
		err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.PauseWorkflowSignal, signalPayload)
		if err == nil {
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), taskID, "paused", "")
			currentTaskState = "PAUSED"
		}
	case "resume":
		err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.ResumeWorkflowSignal, signalPayload)
		if err == nil {
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), taskID, "running", "")
			currentTaskState = "RUNNING"
		}
	case "cancel":
		err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.CancelWorkflowSignal, signalPayload)
		if err == nil {
			err = s.temporal.CancelWorkflow(r.Context(), taskID, "")
		}
	}
	if err != nil {
		writeAPIError(w, http.StatusBadRequest, errCodeInvalidTransition, err.Error(), map[string]any{
			"session_id": sessionID,
			"task_id":    taskID,
			"action":     action,
		})
		return
	}

	controlState := controlStateFromTaskState(currentTaskState)
	if action == "cancel" {
		controlState = "TERMINATING"
	}
	statusCode := http.StatusOK
	if action == "cancel" {
		statusCode = http.StatusAccepted
	}
	writeJSON(w, statusCode, map[string]any{
		"session_id":            sessionID,
		"active_task_id":        taskID,
		"task_state":            currentTaskState,
		"session_control_state": controlState,
		"version":               0,
		"result":                "applied",
	})
}

func normalizeSessionStatusPtr(status *string) string {
	if status == nil {
		return "idle"
	}
	switch strings.ToLower(strings.TrimSpace(*status)) {
	case "pending", "queued", "running":
		return "running"
	case "failed", "error":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	case "paused":
		return "paused"
	case "completed", "success":
		return "completed"
	default:
		return "idle"
	}
}

func (s *Server) handleSessionState(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	row, err := s.sessionDB.GetSession(r.Context(), sessionID, userID)
	if err != nil || row == nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := s.sessionDB.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session state", http.StatusInternalServerError)
		return
	}
	activeTaskID := ""
	status := normalizeSessionStatusPtr(row.LatestTaskStatus)
	taskState := "IDLE"
	sessionControlState := "IDLE"
	if len(tasks) > 0 {
		last := tasks[len(tasks)-1]
		status = normalizeSessionStatusPtr(last.Status)
		if activeTask, ok := resolveSessionActiveTask(tasks); ok {
			activeTaskID = activeTask.WorkflowID
			taskState = normalizeTaskStateForControl(valueFromPtr(activeTask.Status))
			sessionControlState = controlStateFromTaskState(taskState)
		} else {
			taskState = normalizeTaskStateForControl(valueFromPtr(last.Status))
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"session_id":            sessionID,
		"status":                status,
		"active_task_id":        activeTaskID,
		"task_state":            taskState,
		"session_control_state": sessionControlState,
		"version":               0,
		"updated_at":            row.UpdatedAt.UTC().Format(time.RFC3339),
	})
}

func valueFromPtr(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}

func parsePayloadText(raw *string) any {
	if raw == nil || *raw == "" {
		return nil
	}
	var out any
	if err := json.Unmarshal([]byte(*raw), &out); err == nil {
		return out
	}
	return *raw
}

func normalizeWorkspaceResponse(raw map[string]any, sessionID string) map[string]any {
	out := map[string]any{
		"session_id":        sessionID,
		"version":           0,
		"status":            "not_started",
		"card_count":        0,
		"cards":             []map[string]any{},
		"projection_status": "empty",
	}
	if raw == nil {
		return out
	}
	if sid, ok := raw["session_id"].(string); ok && strings.TrimSpace(sid) != "" {
		out["session_id"] = sid
	}
	if v, ok := raw["version"].(float64); ok {
		out["version"] = int(v)
	} else if v, ok := raw["version"].(int); ok {
		out["version"] = v
	}
	if status, ok := raw["status"].(string); ok && strings.TrimSpace(status) != "" {
		out["status"] = status
	}

	cardsRaw, _ := raw["cards"].([]any)
	cards := make([]map[string]any, 0, len(cardsRaw))
	for _, entry := range cardsRaw {
		card, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		id, _ := card["id"].(string)
		userID, _ := card["user_id"].(string)
		cardID, _ := card["card_id"].(string)
		content, _ := card["content"].(map[string]any)
		editState, _ := card["edit_state"].(map[string]any)
		meta, _ := card["meta"].(map[string]any)
		if id == "" || userID == "" || cardID == "" || content == nil || editState == nil || meta == nil {
			continue
		}
		status, _ := editState["status"].(string)
		if status != "draft" && status != "ai_editing" && status != "user_editing" && status != "confirmed" {
			continue
		}
		data, _ := content["data"].(map[string]any)
		if data == nil {
			continue
		}
		if _, ok := data["front"].(string); !ok {
			continue
		}
		if _, ok := data["back"].(string); !ok {
			continue
		}
		cards = append(cards, card)
	}
	out["cards"] = cards
	out["card_count"] = len(cards)
	if len(cards) > 0 {
		out["projection_status"] = "hydrated"
	}
	return out
}
