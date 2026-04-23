package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	v1adapters "task-orchestrator/internal/controller/http/v1/adapters"
	"task-orchestrator/internal/usecase"
)

type SessionsDeps struct {
	WriteJSON     func(w http.ResponseWriter, status int, v any)
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string

	ReadModel         *usecase.ReadModelService
	WorkflowSvc       *usecase.WorkflowService
	CommandService    *usecase.CommandService
	IsTemporalEnabled func() bool

	AuthzDeniedCode string
}

func NewSessionsHandler(deps SessionsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := deps.UserID(r)
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
		list, total, err := deps.ReadModel.ListSessions(r.Context(), userID, limit, offset)
		if err != nil {
			http.Error(w, "failed to list sessions", http.StatusInternalServerError)
			return
		}
		sessions := make([]map[string]any, 0, len(list))
		for _, row := range list {
			sessions = append(sessions, sessionRowToResponse(row))
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{"sessions": sessions, "total_count": total})
	}
}

func NewSessionsRouter(deps SessionsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/sessions/"), "/")
		if trimmed == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(trimmed, "/")
		sessionID := parts[0]
		if len(parts) == 1 {
			handleSessionDetail(w, r, sessionID, deps)
			return
		}
		suffix := parts[1]
		switch suffix {
		case "conversation":
			handleSessionConversation(w, r, sessionID, deps)
		case "timeline":
			handleSessionTimeline(w, r, sessionID, deps)
		case "history":
			handleSessionHistory(w, r, sessionID, deps)
		case "workspace":
			handleSessionWorkspace(w, r, sessionID, deps)
		case "state":
			handleSessionState(w, r, sessionID, deps)
		default:
			http.NotFound(w, r)
		}
	}
}

func handleSessionDetail(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	switch r.Method {
	case http.MethodGet:
		rec, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID)
		if err != nil || rec == nil {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, sessionRowToResponse(*rec))
	case http.MethodPatch:
		var req struct {
			Title  *string `json:"title"`
			Pinned *bool   `json:"pinned"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.Title == nil && req.Pinned == nil {
			http.Error(w, "no fields to update", http.StatusBadRequest)
			return
		}
		if err := deps.ReadModel.UpdateSessionMeta(r.Context(), sessionID, userID, req.Title, req.Pinned); err != nil {
			http.Error(w, "failed to update session", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	case http.MethodDelete:
		affected, err := deps.ReadModel.DeleteSession(r.Context(), sessionID, userID)
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

func sessionRowToResponse(row usecase.SessionRow) map[string]any {
	resp := map[string]any{
		"session_id":     row.SessionID,
		"user_id":        row.UserID,
		"pinned":         row.Pinned,
		"task_count":     row.TaskCount,
		"tokens_used":    row.TokensUsed,
		"total_cost_usd": row.TotalCostUSD,
		"created_at":     row.CreatedAt.UTC().Format(time.RFC3339),
		"updated_at":     row.UpdatedAt.UTC().Format(time.RFC3339),
	}
	if row.Title != nil {
		resp["title"] = *row.Title
	}
	if row.LastActivityAt != nil {
		resp["last_activity_at"] = row.LastActivityAt.UTC().Format(time.RFC3339)
	}
	if row.LatestTaskQuery != nil {
		resp["latest_task_query"] = *row.LatestTaskQuery
	}
	if row.LatestTaskStatus != nil {
		resp["latest_task_status"] = *row.LatestTaskStatus
	}
	return resp
}

func handleSessionConversation(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session history", http.StatusInternalServerError)
		return
	}
	events, err := deps.ReadModel.ListSessionEvents(r.Context(), sessionID, 2000, 0)
	if err != nil {
		http.Error(w, "failed to load session events", http.StatusInternalServerError)
		return
	}
	eventsByTask := make(map[string][]usecase.EventRow)
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
		userMessage := map[string]any{
			"id":        fmt.Sprintf("user-%s", taskID),
			"role":      "user",
			"content":   valueFromPtr(t.Query),
			"timestamp": timestamp,
			"task_id":   taskID,
		}
		if attachments := extractUserAttachmentsFromEvents(eventsByTask[taskID]); len(attachments) > 0 {
			userMessage["attachments"] = attachments
		}
		messages = append(messages, userMessage)
		assistantContent := ExtractResultMessage(t.Result)
		if assistantContent == "" {
			if text, ts := extractAssistantContentFromEvents(eventsByTask[taskID]); text != "" {
				assistantContent = text
				if !ts.IsZero() {
					timestamp = ts.UTC().Format(time.RFC3339)
				}
			}
		}
		if assistantContent != "" {
			messages = append(messages, map[string]any{"id": fmt.Sprintf("assistant-%s", taskID), "role": "assistant", "content": assistantContent, "timestamp": timestamp, "task_id": taskID})
		} else if strings.EqualFold(valueFromPtr(t.Status), "cancelled") {
			messages = append(messages, map[string]any{"id": fmt.Sprintf("assistant-%s", taskID), "role": "assistant", "content": "This task was cancelled.", "timestamp": timestamp, "task_id": taskID})
		}
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "messages": messages})
}

func extractUserAttachmentsFromEvents(events []usecase.EventRow) []map[string]any {
	for i := len(events) - 1; i >= 0; i-- {
		ev := events[i]
		if ev.Payload == nil || strings.TrimSpace(*ev.Payload) == "" {
			continue
		}
		payload := parsePayloadText(ev.Payload)
		record, ok := payload.(map[string]any)
		if !ok {
			continue
		}

		if attachments := normalizeAttachmentsAny(record["attachments"]); len(attachments) > 0 {
			return attachments
		}
		if input, ok := record["input"].(map[string]any); ok {
			if attachments := normalizeAttachmentsAny(input["attachments"]); len(attachments) > 0 {
				return attachments
			}
			if attachments := fileIDsToAttachments(input["file_ids"]); len(attachments) > 0 {
				return attachments
			}
		}
		if attachments := fileIDsToAttachments(record["file_ids"]); len(attachments) > 0 {
			return attachments
		}
	}
	return nil
}

func normalizeAttachmentsAny(value any) []map[string]any {
	list, ok := value.([]any)
	if !ok || len(list) == 0 {
		return nil
	}
	out := make([]map[string]any, 0, len(list))
	for _, entry := range list {
		rec, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		fileID := strings.TrimSpace(asStringAny(rec["file_id"]))
		filename := strings.TrimSpace(asStringAny(rec["filename"]))
		if fileID == "" || filename == "" {
			continue
		}
		size := asInt64Any(rec["size"])
		if size < 0 {
			size = 0
		}
		mimeType := strings.TrimSpace(asStringAny(rec["mime_type"]))
		if mimeType == "" {
			mimeType = "application/octet-stream"
		}
		out = append(out, map[string]any{
			"file_id":   fileID,
			"filename":  filename,
			"size":      size,
			"mime_type": mimeType,
		})
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func fileIDsToAttachments(value any) []map[string]any {
	list, ok := value.([]any)
	if !ok || len(list) == 0 {
		return nil
	}
	out := make([]map[string]any, 0, len(list))
	for _, entry := range list {
		fileID := strings.TrimSpace(asStringAny(entry))
		if fileID == "" {
			continue
		}
		out = append(out, map[string]any{
			"file_id":   fileID,
			"filename":  fileID,
			"size":      int64(0),
			"mime_type": "application/octet-stream",
		})
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func asStringAny(v any) string {
	switch val := v.(type) {
	case string:
		return val
	case fmt.Stringer:
		return val.String()
	default:
		return ""
	}
}

func asInt64Any(v any) int64 {
	switch val := v.(type) {
	case int:
		return int64(val)
	case int32:
		return int64(val)
	case int64:
		return val
	case float64:
		return int64(val)
	default:
		return 0
	}
}

func handleSessionTimeline(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
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
	events, err := deps.ReadModel.ListSessionEvents(r.Context(), sessionID, limit, offset)
	if err != nil {
		http.Error(w, "failed to load session events", http.StatusInternalServerError)
		return
	}
	selected := make([]map[string]any, 0, len(events))
	for _, ev := range events {
		item := map[string]any{
			"id":        ev.ID,
			"type":      ev.Type,
			"timestamp": ev.Timestamp.UTC().Format(time.RFC3339),
		}
		if ev.Message != nil {
			item["message"] = *ev.Message
		}
		if ev.Workflow != nil {
			item["workflow_id"] = *ev.Workflow
		}
		if ev.TaskID != nil {
			item["task_id"] = *ev.TaskID
		}
		if ev.StreamID != nil {
			item["stream_id"] = *ev.StreamID
		}
		if includePayload {
			item["payload"] = parsePayloadText(ev.Payload)
		}
		selected = append(selected, item)
	}
	status := "empty"
	if len(selected) > 0 {
		status = "hydrated"
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "events": selected, "projection_status": status})
}

func handleSessionHistory(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session history", http.StatusInternalServerError)
		return
	}
	usageByTask, err := deps.ReadModel.GetTaskUsageSummaryMapBySession(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load usage summary", http.StatusInternalServerError)
		return
	}
	items := make([]map[string]any, 0, len(tasks))
	for _, t := range tasks {
		usage := usageByTask[t.TaskID]
		status, reason := usageProjectionStatus(t, usage, time.Now().UTC())
		metadata, modelUsed, provider := buildUsageMetadata(usage)
		item := map[string]any{
			"task_id":                 t.TaskID,
			"workflow_id":             t.WorkflowID,
			"query":                   valueFromPtr(t.Query),
			"status":                  valueFromPtr(t.Status),
			"mode":                    valueFromPtr(t.TaskType),
			"total_tokens":            usage.TotalTokens,
			"total_cost_usd":          usage.TotalCostUSD,
			"usage_projection_status": status,
			"usage_projection_reason": reason,
		}
		if modelUsed != "" {
			item["model_used"] = modelUsed
		}
		if provider != "" {
			item["provider"] = provider
		}
		if metadata != nil {
			item["metadata"] = metadata
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
	deps.WriteJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "tasks": items})
}

func usageProjectionStatus(task usecase.TaskRow, usage usecase.TaskUsageSummary, now time.Time) (string, string) {
	if task.CompletedAt == nil {
		return "pending", "task_not_completed"
	}
	hasUsage := usage.TotalTokens > 0 || usage.TotalCostUSD > 0 || len(usage.ModelBreakdown) > 0
	if hasUsage {
		return "finalized", "usage_ingested"
	}
	// Grace window to absorb async projection lag before marking invalid.
	const projectionGrace = 5 * time.Minute
	completedAt := task.CompletedAt.UTC()
	if now.UTC().Sub(completedAt) <= projectionGrace {
		return "partial", "awaiting_usage_projection"
	}
	return "invalid", "usage_missing_after_grace_window"
}

func buildUsageMetadata(usage usecase.TaskUsageSummary) (map[string]any, string, string) {
	if len(usage.ModelBreakdown) == 0 {
		return nil, "", ""
	}
	breakdown := make([]map[string]any, 0, len(usage.ModelBreakdown))
	totalExecutions := 0
	estimatedExecutions := 0
	for _, entry := range usage.ModelBreakdown {
		breakdown = append(breakdown, map[string]any{
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
		totalExecutions += entry.Executions
		estimatedExecutions += entry.EstimatedExecutions
	}

	primary := usage.ModelBreakdown[0]
	estimatedRatio := 0.0
	if totalExecutions > 0 {
		estimatedRatio = float64(estimatedExecutions) / float64(totalExecutions)
	}

	metadata := map[string]any{
		"model":           primary.Model,
		"provider":        primary.Provider,
		"model_breakdown": breakdown,
		"usage_quality": map[string]any{
			"has_estimated_usage": estimatedExecutions > 0,
			"estimated_ratio":     estimatedRatio,
		},
	}
	return metadata, primary.Model, primary.Provider
}

func handleSessionWorkspace(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	resp, err := deps.ReadModel.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	normalized := NormalizeWorkspaceResponse(resp, sessionID)

	needTemplateMetadata := true
	if templateID, ok := normalized["template_id"].(string); ok && strings.TrimSpace(templateID) != "" {
		if supported := normalizeStringSliceAny(normalized["supported_question_types"]); len(supported) > 0 {
			needTemplateMetadata = false
		}
	}
	if needTemplateMetadata {
		tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
		if err == nil {
			for i := len(tasks) - 1; i >= 0; i-- {
				task := tasks[i]
				resultMap, ok := normalizeResultObject(task.Result)
				if !ok || len(resultMap) == 0 {
					continue
				}
				metadata, ok := resultMap["metadata"].(map[string]any)
				if !ok || len(metadata) == 0 {
					continue
				}
				templateID := strings.TrimSpace(asStringAny(metadata["template_id"]))
				if templateID == "" {
					continue
				}
				normalized["template_id"] = templateID
				if supported := normalizeStringSliceAny(metadata["supported_question_types"]); len(supported) > 0 {
					normalized["supported_question_types"] = supported
				}
				selected := strings.TrimSpace(asStringAny(metadata["selected_question_type"]))
				if selected != "" {
					normalized["selected_question_type"] = selected
				}
				break
			}
		}
	}

	deps.WriteJSON(w, http.StatusOK, normalized)
}

func normalizeResultObject(raw any) (map[string]any, bool) {
	if raw == nil {
		return nil, false
	}
	if m, ok := raw.(map[string]any); ok {
		return m, true
	}
	switch v := raw.(type) {
	case []byte:
		var out map[string]any
		if err := json.Unmarshal(v, &out); err == nil && len(out) > 0 {
			return out, true
		}
	case string:
		s := strings.TrimSpace(v)
		if s == "" {
			return nil, false
		}
		var out map[string]any
		if err := json.Unmarshal([]byte(s), &out); err == nil && len(out) > 0 {
			return out, true
		}
	}
	return nil, false
}

func handleSessionState(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	row, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID)
	if err != nil || row == nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
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
		if activeTask, ok := ResolveSessionActiveTask(tasks); ok {
			activeTaskID = activeTask.WorkflowID
			taskState = normalizeTaskStateForControl(valueFromPtr(activeTask.Status))
			sessionControlState = ControlStateFromTaskState(taskState)
		} else {
			taskState = normalizeTaskStateForControl(valueFromPtr(last.Status))
		}
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"session_id":            sessionID,
		"status":                status,
		"active_task_id":        activeTaskID,
		"task_state":            taskState,
		"session_control_state": sessionControlState,
		"version":               0,
		"updated_at":            row.UpdatedAt.UTC().Format(time.RFC3339),
	})
}

func extractAssistantContentFromEvents(events []usecase.EventRow) (string, time.Time) {
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

func ExtractResultMessage(result any) string {
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
			if msg := ExtractResultMessage(parsed); msg != "" {
				return msg
			}
		}
		return text
	case []byte:
		return ExtractResultMessage(string(v))
	case map[string]any:
		if msg, ok := v1adapters.DecodeTaskOutcomeMessage(v); ok {
			return msg
		}
		for _, nestedKey := range []string{"result", "data"} {
			if nested, ok := v[nestedKey]; ok {
				if msg := ExtractResultMessage(nested); msg != "" {
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
			if msg := ExtractResultMessage(item); msg != "" {
				return msg
			}
		}
	}
	return ""
}

func sessionReadFallbackEnabled() bool {
	return strings.EqualFold(strings.TrimSpace(os.Getenv("TASK_READ_PATH_BACKFILL_ENABLED")), "true")
}

func IsTaskActiveStatus(raw string) bool {
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

func ControlStateFromTaskState(taskState string) string {
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

func ResolveSessionActiveTask(tasks []usecase.TaskRow) (usecase.TaskRow, bool) {
	for i := len(tasks) - 1; i >= 0; i-- {
		status := valueFromPtr(tasks[i].Status)
		if IsTaskActiveStatus(status) {
			return tasks[i], true
		}
	}
	return usecase.TaskRow{}, false
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

func NormalizeWorkspaceResponse(raw map[string]any, sessionID string) map[string]any {
	out := map[string]any{"session_id": sessionID, "version": 0, "status": "not_started", "card_count": 0, "cards": []map[string]any{}, "projection_status": "empty"}
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
	if templateID, ok := raw["template_id"].(string); ok && strings.TrimSpace(templateID) != "" {
		out["template_id"] = strings.TrimSpace(templateID)
	}
	if selected, ok := raw["selected_question_type"].(string); ok && strings.TrimSpace(selected) != "" {
		out["selected_question_type"] = strings.TrimSpace(selected)
	}
	if supported := normalizeStringSliceAny(raw["supported_question_types"]); len(supported) > 0 {
		out["supported_question_types"] = supported
	}
	cardsRaw, _ := raw["cards"].([]any)
	cards := make([]map[string]any, 0, len(cardsRaw))
	now := time.Now().UTC().Format(time.RFC3339)
	for _, entry := range cardsRaw {
		card, ok := normalizeWorkspaceCard(entry, now)
		if ok {
			cards = append(cards, card)
		}
	}
	out["cards"] = cards
	out["card_count"] = len(cards)
	if len(cards) > 0 {
		out["projection_status"] = "hydrated"
	}
	return out
}

func normalizeStringSliceAny(v any) []string {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		s, ok := item.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		out = append(out, s)
	}
	return out
}

func normalizeWorkspaceCard(entry any, fallbackTime string) (map[string]any, bool) {
	card, ok := entry.(map[string]any)
	if !ok {
		return nil, false
	}

	cardID := strings.TrimSpace(firstNonEmptyStringAny(card["card_id"], card["id"], card["temp_id"]))
	if cardID == "" {
		return nil, false
	}

	content := asMapAny(card["content"])
	contentData := asMapAny(content["data"])
	front := strings.TrimSpace(firstNonEmptyStringAny(contentData["front"], content["front"]))
	back := strings.TrimSpace(firstNonEmptyStringAny(contentData["back"], content["back"]))

	data := map[string]any{
		"front": front,
		"back":  back,
		"tags":  normalizeStringSliceAny(contentData["tags"]),
	}
	if len(data["tags"].([]string)) == 0 {
		data["tags"] = normalizeStringSliceAny(content["tags"])
	}
	data["concepts"] = normalizeStringSliceAny(contentData["concepts"])
	if len(data["concepts"].([]string)) == 0 {
		data["concepts"] = normalizeStringSliceAny(content["concepts"])
	}

	contentOut := map[string]any{
		"version": asIntAny(firstNonEmptyAny(content["version"], card["version"])),
		"model":   strings.TrimSpace(firstNonEmptyStringAny(content["model"], card["model"])),
		"data":    data,
	}
	if asIntAny(contentOut["version"]) <= 0 {
		contentOut["version"] = 1
	}
	if contentOut["model"] == "" {
		contentOut["model"] = "mcq"
	}
	if media, ok := content["media"].([]any); ok {
		contentOut["media"] = media
	} else if media, ok := card["media"].([]any); ok {
		contentOut["media"] = media
	} else {
		contentOut["media"] = []any{}
	}

	status := normalizeWorkspaceCardStatus(strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["status"],
		card["status"],
	)))
	if status == "" {
		return nil, false
	}
	editStateOut := map[string]any{"status": status}
	if lockedBy := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["locked_by"],
		card["locked_by"],
	)); lockedBy != "" {
		editStateOut["locked_by"] = lockedBy
	}
	if lockedAt := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["locked_at"],
		card["locked_at"],
	)); lockedAt != "" {
		editStateOut["locked_at"] = lockedAt
	}
	if expiresAt := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["expires_at"],
		card["lock_expires"],
	)); expiresAt != "" {
		editStateOut["expires_at"] = expiresAt
	}

	meta := asMapAny(card["meta"])
	createdAt := strings.TrimSpace(firstNonEmptyStringAny(meta["created_at"], card["created_at"], fallbackTime))
	modifiedAt := strings.TrimSpace(firstNonEmptyStringAny(meta["modified_at"], card["modified_at"], fallbackTime))
	metaOut := map[string]any{
		"created_at":   createdAt,
		"modified_at":  modifiedAt,
		"manual_edits": asIntAny(firstNonEmptyAny(meta["manual_edits"], card["manual_edits"])),
	}

	userID := strings.TrimSpace(firstNonEmptyStringAny(card["user_id"], card["owner"], "system"))
	suggestedQuestionType := strings.TrimSpace(firstNonEmptyStringAny(card["suggested_question_type"], contentOut["model"]))

	out := map[string]any{
		"id":                      cardID,
		"user_id":                 userID,
		"card_id":                 cardID,
		"suggested_question_type": suggestedQuestionType,
		"content":                 contentOut,
		"edit_state":              editStateOut,
		"concepts":                data["concepts"],
		"meta":                    metaOut,
	}
	return out, true
}

func normalizeWorkspaceCardStatus(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "draft", "output_draft":
		return "draft"
	case "ai_editing":
		return "ai_editing"
	case "user_editing":
		return "user_editing"
	case "confirmed", "output_confirmed":
		return "confirmed"
	default:
		return ""
	}
}

func asMapAny(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func asIntAny(v any) int {
	switch val := v.(type) {
	case int:
		return val
	case int32:
		return int(val)
	case int64:
		return int(val)
	case float64:
		return int(val)
	default:
		return 0
	}
}

func firstNonEmptyStringAny(values ...any) string {
	for _, value := range values {
		if s, ok := value.(string); ok {
			if strings.TrimSpace(s) != "" {
				return strings.TrimSpace(s)
			}
		}
	}
	return ""
}

func firstNonEmptyAny(values ...any) any {
	for _, value := range values {
		if value == nil {
			continue
		}
		switch typed := value.(type) {
		case string:
			if strings.TrimSpace(typed) == "" {
				continue
			}
		}
		return value
	}
	return nil
}
