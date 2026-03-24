package httpserver

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
)

func (s *Server) workflowStatusHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
	if workflowID == "" {
		http.Error(w, "workflow_id is required", http.StatusBadRequest)
		return
	}
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, workflowID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for workflow resource", map[string]any{
			"workflow_id": workflowID,
		})
		return
	}
	if !s.isTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	runID := strings.TrimSpace(r.URL.Query().Get("run_id"))
	describeResp, err := s.temporal.DescribeWorkflowExecution(r.Context(), workflowID, runID)
	if err != nil {
		http.Error(w, fmt.Sprintf("failed to get workflow status: %v", err), http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"workflow_id": workflowID,
		"run_id":      describeResp.WorkflowExecutionInfo.Execution.RunId,
		"status":      strings.ToLower(strings.TrimPrefix(mapTemporalStatus(describeResp.WorkflowExecutionInfo.Status), "TASK_STATUS_")),
		"start_time":  describeResp.WorkflowExecutionInfo.StartTime.AsTime().UTC().Format(time.RFC3339),
		"close_time": func() string {
			if describeResp.WorkflowExecutionInfo.CloseTime == nil {
				return ""
			}
			return describeResp.WorkflowExecutionInfo.CloseTime.AsTime().UTC().Format(time.RFC3339)
		}(),
	})
}

func (s *Server) workflowCancelHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		WorkflowID string `json:"workflow_id"`
		Reason     string `json:"reason"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if req.WorkflowID == "" {
		http.Error(w, "workflow_id is required", http.StatusBadRequest)
		return
	}
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, req.WorkflowID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for workflow resource", map[string]any{
			"workflow_id": req.WorkflowID,
		})
		return
	}
	if !s.isTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	if err := s.temporal.CancelWorkflow(r.Context(), req.WorkflowID, ""); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if s.sessionDB != nil {
		_ = s.sessionDB.UpdateTaskStatus(r.Context(), req.WorkflowID, "cancelled", req.Reason)
	}
	writeJSON(w, http.StatusOK, map[string]any{"workflow_id": req.WorkflowID, "status": "cancelled", "message": "Workflow cancelled successfully"})
}

func (s *Server) workflowHistoryHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
	if workflowID == "" {
		http.Error(w, "workflow_id is required", http.StatusBadRequest)
		return
	}
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, workflowID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for workflow resource", map[string]any{
			"workflow_id": workflowID,
		})
		return
	}
	if s.isTemporalEnabled() {
		iter := s.temporal.GetWorkflowHistory(r.Context(), workflowID, "", false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
		out := make([]map[string]any, 0)
		for iter.HasNext() {
			ev, err := iter.Next()
			if err != nil {
				break
			}
			out = append(out, map[string]any{
				"event_id":   ev.EventId,
				"event_type": ev.EventType.String(),
				"timestamp":  ev.EventTime.AsTime().UTC().Format(time.RFC3339),
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"workflow_id": workflowID, "events": out, "total_count": len(out)})
		return
	}
	if s.sessionDB == nil {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	events, err := s.sessionDB.ListWorkflowEvents(r.Context(), workflowID, 2000, 0)
	if err != nil {
		http.Error(w, "failed to load workflow events", http.StatusInternalServerError)
		return
	}
	out := make([]map[string]any, 0, len(events))
	for _, ev := range events {
		out = append(out, map[string]any{
			"event_id":   ev.ID,
			"event_type": ev.Type,
			"timestamp":  ev.Timestamp.UTC().Format(time.RFC3339),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"workflow_id": workflowID, "events": out, "total_count": len(out)})
}
