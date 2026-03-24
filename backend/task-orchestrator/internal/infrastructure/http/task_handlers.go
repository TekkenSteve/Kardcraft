package httpserver

import (
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	tclient "go.temporal.io/sdk/client"

	"task-orchestrator/internal/application"
	"task-orchestrator/internal/infrastructure/persistence"
	"task-orchestrator/internal/infrastructure/temporal/workflows"
)

func (s *Server) tasksHandler(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		s.handleListTasks(w, r)
	case http.MethodPost:
		s.handleCreateTask(w, r)
	case http.MethodOptions:
		w.WriteHeader(http.StatusOK)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) handleCreateTask(w http.ResponseWriter, r *http.Request) {
	var req struct {
		TaskType string         `json:"task_type"`
		UserID   string         `json:"user_id"`
		Query    string         `json:"query"`
		Input    map[string]any `json:"input"`
		Config   map[string]any `json:"config"`
		Metadata map[string]any `json:"metadata"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if req.Input == nil {
		req.Input = map[string]any{}
	}
	if req.Config == nil {
		req.Config = map[string]any{}
	}
	if req.Metadata == nil {
		req.Metadata = map[string]any{}
	}
	if strings.TrimSpace(req.Query) == "" {
		if q, ok := req.Input["query"].(string); ok {
			req.Query = strings.TrimSpace(q)
		}
	}
	if strings.TrimSpace(req.Query) == "" {
		http.Error(w, "query is required", http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(req.TaskType) == "" {
		req.TaskType = "main"
	}
	if req.TaskType == "main" {
		ctxRaw, ok := req.Input["context"]
		if !ok {
			http.Error(w, "template_id is required in input.context for main task", http.StatusBadRequest)
			return
		}
		ctxMap, ok := ctxRaw.(map[string]any)
		if !ok {
			http.Error(w, "input.context must be an object", http.StatusBadRequest)
			return
		}
		templateID, _ := ctxMap["template_id"].(string)
		if strings.TrimSpace(templateID) == "" {
			http.Error(w, "template_id is required in input.context for main task", http.StatusBadRequest)
			return
		}
	}
	userID := userIDFromContext(r.Context())
	sessionID := ""
	if raw, ok := req.Input["session_id"].(string); ok {
		sessionID = strings.TrimSpace(raw)
	}
	if sessionID == "" {
		sessionID = fmt.Sprintf("session_%d", time.Now().UTC().UnixNano())
	}
	req.Input["session_id"] = sessionID
	req.Input["query"] = req.Query
	if !s.isTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}

	workflowID := s.nextWorkflowID(req.TaskType)
	if err := s.sessionDB.UpsertSession(r.Context(), sessionID, userID, req.Query, "pending"); err != nil {
		http.Error(w, "failed to persist session", http.StatusInternalServerError)
		return
	}
	inserted, err := s.sessionDB.InsertTaskIfNoActive(r.Context(), workflowID, sessionID, userID, req.TaskType, "pending", req.Query)
	if err != nil {
		log.Printf("create task persist failed session_id=%s user_id=%s task_id=%s err=%v", sessionID, userID, workflowID, err)
		http.Error(w, "failed to persist task", http.StatusInternalServerError)
		return
	}
	if !inserted {
		recheckTasks, recheckErr := s.sessionDB.ListSessionTasks(r.Context(), sessionID, userID)
		if recheckErr != nil {
			http.Error(w, "failed to inspect active task conflict", http.StatusInternalServerError)
			return
		}
		details := map[string]any{"session_id": sessionID}
		if activeTask, ok := resolveSessionActiveTask(recheckTasks); ok {
			details["active_task_id"] = activeTask.TaskID
		}
		writeAPIError(w, http.StatusConflict, errCodeActiveTaskExists, "session already has an active task", details)
		return
	}
	_, err = s.taskService.CreateTask(r.Context(), application.CreateTaskInput{
		TaskID:    workflowID,
		TaskType:  req.TaskType,
		UserID:    userID,
		Query:     req.Query,
		SessionID: sessionID,
	})
	if err != nil {
		_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "failed", err.Error())
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	runID := fmt.Sprintf("run_%d", time.Now().UTC().UnixNano())
	req.Input["session_id"] = sessionID
	workflowInput := workflows.TaskInput{
		TaskID:   workflowID,
		UserID:   userID,
		TaskType: req.TaskType,
		Input:    req.Input,
		Config:   req.Config,
		Metadata: req.Metadata,
	}
	workflowRun, err := s.temporal.ExecuteWorkflow(r.Context(), tclient.StartWorkflowOptions{
		ID:                  workflowID,
		TaskQueue:           s.taskQueue,
		WorkflowRunTimeout:  30 * time.Minute,
		WorkflowTaskTimeout: 10 * time.Second,
	}, workflows.TaskWorkflow, workflowInput)
	if err != nil {
		_ = s.sessionDB.UpdateTaskStatus(r.Context(), workflowID, "failed", err.Error())
		http.Error(w, fmt.Sprintf("failed to start workflow: %v", err), http.StatusInternalServerError)
		return
	}
	runID = workflowRun.GetRunID()
	s.ensureWorkflowStreamReader(workflowID)

	writeJSON(w, http.StatusCreated, map[string]any{
		"workflow_id": workflowID,
		"run_id":      runID,
		"status":      "pending",
		"message":     "Task created and workflow started successfully",
		"created_at":  nowRFC3339(),
		"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", workflowID),
		"session_id":  sessionID,
	})
}

func (s *Server) handleListTasks(w http.ResponseWriter, r *http.Request) {
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

	userID := userIDFromContext(r.Context())
	items, total, err := s.taskService.ListTasks(r.Context(), application.ListTasksInput{UserID: userID, Limit: limit, Offset: offset})
	if err != nil {
		http.Error(w, "failed to list tasks", http.StatusInternalServerError)
		return
	}
	taskIDs := make([]string, 0, len(items))
	for _, t := range items {
		taskIDs = append(taskIDs, t.ID().String())
	}
	usageByTask := map[string]persistence.TaskUsageSummary{}
	if s.sessionDB != nil && len(taskIDs) > 0 {
		usageByTask, err = s.sessionDB.GetTaskUsageSummaryMapByTaskIDs(r.Context(), userID, taskIDs)
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
			"status":      mapTaskStatus(t),
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

	writeJSON(w, http.StatusOK, map[string]any{
		"tasks":       tasks,
		"total_count": total,
	})
}

func (s *Server) taskDetailRouter(w http.ResponseWriter, r *http.Request) {
	path := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/tasks/"), "/")
	if path == "" {
		http.NotFound(w, r)
		return
	}
	parts := strings.Split(path, "/")
	if len(parts) == 1 {
		if r.Method == http.MethodGet {
			s.handleGetTask(w, r, parts[0])
			return
		}
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if len(parts) == 2 {
		s.handleTaskControl(w, r, parts[0], parts[1])
		return
	}
	http.NotFound(w, r)
}

func (s *Server) handleGetTask(w http.ResponseWriter, r *http.Request, taskID string) {
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, taskID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for task resource", map[string]any{
			"task_id": taskID,
		})
		return
	}
	if !s.isTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	describeResp, err := s.temporal.DescribeWorkflowExecution(r.Context(), taskID, "")
	if err != nil {
		http.Error(w, "task not found", http.StatusNotFound)
		return
	}
	status := mapTemporalStatus(describeResp.WorkflowExecutionInfo.Status)
	sessionID := ""
	if s.sessionDB != nil {
		if sid, err := s.sessionDB.GetTaskSession(r.Context(), taskID); err == nil {
			sessionID = sid
		}
	}
	response := map[string]any{
		"workflow_id": taskID,
		"task_id":     taskID,
		"task_type":   "main",
		"query":       "",
		"status":      status,
		"created_at":  describeResp.WorkflowExecutionInfo.StartTime.AsTime().UTC().Format(time.RFC3339),
		"session_id":  sessionID,
		"metadata": map[string]any{
			"task_context": map[string]any{},
		},
	}
	if describeResp.WorkflowExecutionInfo.CloseTime != nil {
		response["finished_at"] = describeResp.WorkflowExecutionInfo.CloseTime.AsTime().UTC().Format(time.RFC3339)
	}
	if describeResp.WorkflowExecutionInfo.Status == enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED {
		runID := describeResp.WorkflowExecutionInfo.Execution.RunId
		wr := s.temporal.GetWorkflow(r.Context(), taskID, runID)
		var result any
		if err := wr.Get(r.Context(), &result); err == nil {
			response["result"] = result
		}
	}
	writeJSON(w, http.StatusOK, response)
}

func (s *Server) handleTaskControl(w http.ResponseWriter, r *http.Request, taskID string, action string) {
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, taskID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for task resource", map[string]any{
			"task_id": taskID,
		})
		return
	}
	if action == "control-state" {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		s.handleTaskControlState(w, r, taskID)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		Reason string `json:"reason"`
	}
	_ = parseJSON(r, &req)

	var err error
	if s.isTemporalEnabled() {
		signalPayload := map[string]any{
			"reason":     req.Reason,
			"request_by": userID,
			"timestamp":  time.Now().UTC(),
		}
		switch action {
		case "pause":
			err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.PauseWorkflowSignal, signalPayload)
		case "resume":
			err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.ResumeWorkflowSignal, signalPayload)
		case "cancel":
			err = s.temporal.SignalWorkflow(r.Context(), taskID, "", workflows.CancelWorkflowSignal, signalPayload)
			if err == nil {
				err = s.temporal.CancelWorkflow(r.Context(), taskID, "")
			}
		default:
			http.Error(w, "unsupported action", http.StatusBadRequest)
			return
		}
	} else {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"success":     false,
			"message":     err.Error(),
			"workflow_id": taskID,
		})
		return
	}
	if s.sessionDB != nil {
		status := "pending"
		switch action {
		case "pause":
			status = "paused"
		case "resume":
			status = "running"
		case "cancel":
			status = "cancelled"
		}
		_ = s.sessionDB.UpdateTaskStatus(r.Context(), taskID, status, "")
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"success":     true,
		"message":     fmt.Sprintf("Task %s signal sent successfully", action),
		"workflow_id": taskID,
	})
}

func (s *Server) handleTaskControlState(w http.ResponseWriter, r *http.Request, taskID string) {
	if s.isTemporalEnabled() {
		isPaused := false
		isCancelled := false
		pausedAt := ""
		pauseReason := ""
		cancelReason := ""
		queryResp, err := s.temporal.QueryWorkflow(r.Context(), taskID, "", "get-workflow-state")
		if err == nil {
			var st workflows.WorkflowState
			if err := queryResp.Get(&st); err == nil {
				isPaused = st.IsPaused
				isCancelled = st.IsCancelled
				if !st.PausedAt.IsZero() {
					pausedAt = st.PausedAt.UTC().Format(time.RFC3339)
				}
				pauseReason = st.PauseReason
				cancelReason = st.CancelReason
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"is_paused":     isPaused,
			"is_cancelled":  isCancelled,
			"paused_at":     pausedAt,
			"pause_reason":  pauseReason,
			"paused_by":     userIDFromContext(r.Context()),
			"cancel_reason": cancelReason,
			"cancelled_by":  userIDFromContext(r.Context()),
		})
		return
	}

	http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
}

func (s *Server) batchTasksHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		BatchID string `json:"batch_id"`
		Tasks   []struct {
			TaskType string         `json:"task_type"`
			Query    string         `json:"query"`
			Input    map[string]any `json:"input"`
		} `json:"tasks"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if len(req.Tasks) == 0 {
		http.Error(w, "tasks array is required", http.StatusBadRequest)
		return
	}
	if req.BatchID == "" {
		req.BatchID = fmt.Sprintf("batch_%d", time.Now().UTC().UnixNano())
	}
	workflowID := fmt.Sprintf("batch_workflow_%s", req.BatchID)
	runID := fmt.Sprintf("run_%d", time.Now().UTC().UnixNano())
	if s.isTemporalEnabled() {
		userID := userIDFromContext(r.Context())
		input := map[string]any{
			"batch_id": req.BatchID,
			"tasks":    req.Tasks,
		}
		workflowInput := workflows.TaskInput{
			TaskID:   workflowID,
			UserID:   userID,
			TaskType: "batch",
			Input:    input,
			Config:   map[string]any{},
			Metadata: map[string]any{},
		}
		wr, err := s.temporal.ExecuteWorkflow(r.Context(), tclient.StartWorkflowOptions{
			ID:                  workflowID,
			TaskQueue:           s.taskQueue,
			WorkflowRunTimeout:  2 * time.Hour,
			WorkflowTaskTimeout: 10 * time.Second,
		}, workflows.TaskWorkflow, workflowInput)
		if err == nil {
			runID = wr.GetRunID()
		}
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"batch_id":    req.BatchID,
		"workflow_id": workflowID,
		"run_id":      runID,
		"status":      "pending",
		"total_tasks": len(req.Tasks),
		"message":     "Batch workflow started successfully",
		"created_at":  nowRFC3339(),
		"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", workflowID),
	})
}

func (s *Server) templateTasksHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method == http.MethodGet {
		if s.sessionDB == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := userIDFromContext(r.Context())
		rows, total, err := s.sessionDB.ListAccessibleTemplates(r.Context(), userID, 100, 0)
		if err != nil {
			http.Error(w, "failed to list templates", http.StatusInternalServerError)
			return
		}
		templates := make([]map[string]any, 0, len(rows))
		for _, row := range rows {
			templates = append(templates, map[string]any{
				"id":          row.TemplateID,
				"name":        row.Name,
				"description": row.Description,
				"version":     row.LatestVersion,
				"category":    "general",
				"tags":        row.Tags,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"templates": templates, "total_count": total})
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		TemplateID string         `json:"template_id"`
		Variables  map[string]any `json:"variables"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(req.TemplateID) == "" {
		http.Error(w, "template_id is required", http.StatusBadRequest)
		return
	}
	workflowID := fmt.Sprintf("template_workflow_%s_%d", req.TemplateID, time.Now().UTC().UnixNano())
	runID := fmt.Sprintf("run_%d", time.Now().UTC().UnixNano())
	if s.isTemporalEnabled() {
		userID := userIDFromContext(r.Context())
		workflowInput := workflows.TaskInput{
			TaskID:   workflowID,
			UserID:   userID,
			TaskType: "template",
			Input: map[string]any{
				"template_id": req.TemplateID,
				"variables":   req.Variables,
			},
			Config:   map[string]any{},
			Metadata: map[string]any{},
		}
		wr, err := s.temporal.ExecuteWorkflow(r.Context(), tclient.StartWorkflowOptions{
			ID:                  workflowID,
			TaskQueue:           s.taskQueue,
			WorkflowRunTimeout:  time.Hour,
			WorkflowTaskTimeout: 10 * time.Second,
		}, workflows.TaskWorkflow, workflowInput)
		if err == nil {
			runID = wr.GetRunID()
		}
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"workflow_id": workflowID,
		"run_id":      runID,
		"status":      "pending",
		"message":     fmt.Sprintf("Template workflow started with template: %s", req.TemplateID),
		"created_at":  nowRFC3339(),
		"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", workflowID),
	})
}
