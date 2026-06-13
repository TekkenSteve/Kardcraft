package v1

import (
	"encoding/json"
	"net/http"
	"strings"
)

type WorkflowsDeps struct {
	WriteJSON     func(w http.ResponseWriter, status int, v any)
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string
	Authorize     func(r *http.Request, userID, workflowID string) bool

	Status  func(r *http.Request, workflowID, runID string) (map[string]any, error)
	Cancel  func(r *http.Request, workflowID, reason string) error
	History func(r *http.Request, workflowID string) ([]map[string]any, error)
}

func NewWorkflowStatusHandler(deps WorkflowsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
		if workflowID == "" {
			http.Error(w, "workflow_id is required", http.StatusBadRequest)
			return
		}
		userID := deps.UserID(r)
		if !deps.Authorize(r, userID, workflowID) {
			deps.WriteAPIError(w, http.StatusForbidden, "authz-denied", "access denied for workflow resource", map[string]any{
				"workflow_id": workflowID,
			})
			return
		}
		runID := strings.TrimSpace(r.URL.Query().Get("run_id"))
		resp, err := deps.Status(r, workflowID, runID)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		deps.WriteJSON(w, http.StatusOK, resp)
	}
}

func NewWorkflowCancelHandler(deps WorkflowsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			WorkflowID string `json:"workflow_id"`
			Reason     string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.WorkflowID) == "" {
			http.Error(w, "workflow_id is required", http.StatusBadRequest)
			return
		}
		userID := deps.UserID(r)
		if !deps.Authorize(r, userID, req.WorkflowID) {
			deps.WriteAPIError(w, http.StatusForbidden, "authz-denied", "access denied for workflow resource", map[string]any{
				"workflow_id": req.WorkflowID,
			})
			return
		}
		if err := deps.Cancel(r, req.WorkflowID, req.Reason); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"workflow_id": req.WorkflowID,
			"status":      "cancelled",
			"message":     "Workflow cancelled successfully",
		})
	}
}

func NewWorkflowHistoryHandler(deps WorkflowsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
		if workflowID == "" {
			http.Error(w, "workflow_id is required", http.StatusBadRequest)
			return
		}
		userID := deps.UserID(r)
		if !deps.Authorize(r, userID, workflowID) {
			deps.WriteAPIError(w, http.StatusForbidden, "authz-denied", "access denied for workflow resource", map[string]any{
				"workflow_id": workflowID,
			})
			return
		}
		events, err := deps.History(r, workflowID)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"workflow_id": workflowID,
			"events":      events,
			"total_count": len(events),
		})
	}
}
