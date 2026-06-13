package v1

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

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
