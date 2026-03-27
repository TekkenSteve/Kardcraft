package handlers

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

type EventsDeps struct {
	WriteJSON      func(w http.ResponseWriter, status int, v any)
	ResolveSession func(r *http.Request, workflowID string) string
	AppendTimeline func(workflowID, sessionID, eventType, message string, payload any)
}

func NewEventsHandler(deps EventsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "failed to read body", http.StatusBadRequest)
			return
		}
		defer r.Body.Close()
		payload := map[string]any{}
		if len(body) > 0 {
			if err := json.Unmarshal(body, &payload); err != nil {
				workflowID := strings.TrimSpace(r.Header.Get("X-Workflow-ID"))
				if workflowID == "" {
					http.Error(w, "workflow_id required in JSON body or X-Workflow-ID header", http.StatusBadRequest)
					return
				}
				deps.AppendTimeline(workflowID, "", "WORKFLOW_PROGRESS", string(body), map[string]any{"raw": string(body)})
				deps.WriteJSON(w, http.StatusAccepted, map[string]any{"status": "ok"})
				return
			}
		}
		workflowID, _ := payload["workflow_id"].(string)
		if workflowID == "" {
			workflowID = strings.TrimSpace(r.Header.Get("X-Workflow-ID"))
		}
		if workflowID == "" {
			http.Error(w, "workflow_id required", http.StatusBadRequest)
			return
		}
		eventType, _ := payload["type"].(string)
		if eventType == "" {
			eventType, _ = payload["event_type"].(string)
		}
		if eventType == "" {
			eventType = "WORKFLOW_PROGRESS"
		}
		message, _ := payload["message"].(string)
		sessionID := deps.ResolveSession(r, workflowID)
		deps.AppendTimeline(workflowID, sessionID, eventType, message, payload)
		deps.WriteJSON(w, http.StatusAccepted, map[string]any{"status": "ok"})
	}
}
