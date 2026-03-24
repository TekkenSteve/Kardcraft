package httpserver

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

func (s *Server) eventsHandler(w http.ResponseWriter, r *http.Request) {
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
			s.appendTimeline(workflowID, "", "WORKFLOW_PROGRESS", string(body), map[string]any{"raw": string(body)})
			writeJSON(w, http.StatusAccepted, map[string]any{"status": "ok"})
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
	taskObj, _ := s.taskService.GetTask(r.Context(), workflowID)
	sessionID := ""
	if taskObj != nil {
		sessionID = taskObj.SessionID()
	} else if s.sessionDB != nil {
		if sid, err := s.sessionDB.GetTaskSession(r.Context(), workflowID); err == nil {
			sessionID = sid
		}
	}
	if s.sessionDB != nil {
		switch strings.ToUpper(eventType) {
		case "WORKFLOW_STARTED":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "running", "")
		case "WORKFLOW_COMPLETED", "DONE":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "completed", "")
		case "WORKFLOW_FAILED":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "failed", message)
		case "WORKFLOW_CANCELLED":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "cancelled", message)
		case "WORKFLOW_PAUSED":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "paused", message)
		case "WORKFLOW_RESUMED":
			_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "running", "")
		}
	}
	s.appendTimeline(workflowID, sessionID, eventType, message, payload)
	writeJSON(w, http.StatusAccepted, map[string]any{"status": "ok"})
}
