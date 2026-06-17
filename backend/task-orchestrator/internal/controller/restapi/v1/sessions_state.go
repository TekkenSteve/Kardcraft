package v1

import (
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

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
		if msg != "" && (ev.Type == usecase.EventWorkflowCompleted || ev.Type == usecase.EventThreadMessageCompleted || ev.Type == usecase.EventLLMOutput) {
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
		if msg, ok := DecodeTaskOutcomeMessage(v); ok {
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
