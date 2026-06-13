package v1

import (
	"net/http"
	"strconv"
	"strings"
	"time"
)

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
		payload := parsePayloadText(ev.Payload)
		eventPayload, runID := timelineEventPayload(payload)
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
		if runID != "" {
			item["run_id"] = runID
		}
		if ev.TaskID != nil {
			item["task_id"] = *ev.TaskID
		}
		if ev.StreamID != nil {
			item["stream_id"] = *ev.StreamID
		}
		if includePayload {
			item["payload"] = eventPayload
		}
		selected = append(selected, item)
	}
	status := "empty"
	if len(selected) > 0 {
		status = "hydrated"
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "events": selected, "projection_status": status})
}

func timelineEventPayload(payload any) (any, string) {
	record, ok := payload.(map[string]any)
	if !ok {
		return payload, ""
	}
	runID := strings.TrimSpace(stringField(record, "run_id"))
	if nested, ok := record["payload"].(map[string]any); ok {
		if runID == "" {
			runID = strings.TrimSpace(stringField(nested, "run_id"))
		}
		return nested, runID
	}
	return record, runID
}

func stringField(record map[string]any, key string) string {
	value, ok := record[key].(string)
	if !ok {
		return ""
	}
	return value
}
