package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	httpdto "task-orchestrator/internal/controller/http/v1/dto"
	v1support "task-orchestrator/internal/controller/http/v1/support"
	"task-orchestrator/internal/usecase"
	ucdto "task-orchestrator/internal/usecase/dto"
)

type TasksDeps struct {
	WriteJSON     func(w http.ResponseWriter, status int, v any)
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	NowRFC3339    func() string
	UserID        func(r *http.Request) string

	TaskService    *usecase.TaskService
	CommandService *usecase.CommandService
	ReadModel      *usecase.ReadModelService
	WorkflowSvc    *usecase.WorkflowService

	IsTemporalEnabled          func() bool
	NextWorkflowID             func(taskType string) string
	EnsureWorkflowStreamReader func(workflowID string)
	AuthorizeTaskAccess        func(r *http.Request, userID, taskID string) bool

	ActiveTaskCode  string
	AuthzDeniedCode string
	IdempotencyRequiredCode string
}

func NewTasksHandler(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			handleListTasks(w, r, deps)
		case http.MethodPost:
			handleCreateTask(w, r, deps)
		case http.MethodOptions:
			w.WriteHeader(http.StatusOK)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func NewTaskDetailRouter(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		path := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/tasks/"), "/")
		if path == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(path, "/")
		if len(parts) == 1 {
			if r.Method == http.MethodGet {
				handleGetTask(w, r, parts[0], deps)
				return
			}
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if len(parts) == 2 {
			handleTaskControl(w, r, parts[0], parts[1], deps)
			return
		}
		http.NotFound(w, r)
	}
}

func NewTemplateTasksHandler(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method == http.MethodGet {
			if deps.ReadModel == nil {
				http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
				return
			}
			userID := deps.UserID(r)
			rows, total, err := deps.ReadModel.ListAccessibleTemplates(r.Context(), userID, 100, 0)
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
			deps.WriteJSON(w, http.StatusOK, map[string]any{"templates": templates, "total_count": total})
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			TemplateID string         `json:"template_id"`
			Variables  map[string]any `json:"variables"`
			SessionID  string         `json:"session_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.TemplateID) == "" {
			http.Error(w, "template_id is required", http.StatusBadRequest)
			return
		}
		if !deps.IsTemporalEnabled() {
			http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
			return
		}
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		if deps.CommandService == nil {
			http.Error(w, "command service unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := deps.UserID(r)
		sessionID := resolveSessionID(req.SessionID)
		workflowID := deps.NextWorkflowID(ucdto.TaskTypeCardTemplate)
		cmd := ucdto.CreateTaskCommand{
			TaskID:    workflowID,
			UserID:    userID,
			TaskType:  ucdto.TaskTypeCardTemplate,
			SessionID: sessionID,
			Query:     fmt.Sprintf("template:%s", strings.TrimSpace(req.TemplateID)),
			Input: ucdto.CreateTaskInput{
				SessionID:  sessionID,
				TemplateID: req.TemplateID,
				Variables:  req.Variables,
			},
			Config: ucdto.CreateTaskConfig{},
			Metadata: ucdto.CreateTaskMetadata{
				Source: "tasks/template",
			},
		}
		createResult, activeTaskID, err := deps.CommandService.CreateTaskInSession(r.Context(), cmd)
		if err != nil {
			if errors.Is(err, usecase.ErrActiveTaskExists) {
				details := map[string]any{"session_id": sessionID}
				if strings.TrimSpace(activeTaskID) != "" {
					details["active_task_id"] = activeTaskID
				}
				deps.WriteAPIError(w, http.StatusConflict, deps.ActiveTaskCode, "session already has an active task", details)
				return
			}
			http.Error(w, fmt.Sprintf("failed to start workflow: %v", err), http.StatusInternalServerError)
			return
		}
		deps.EnsureWorkflowStreamReader(createResult.WorkflowID)
		deps.WriteJSON(w, http.StatusCreated, map[string]any{
			"workflow_id": createResult.WorkflowID,
			"run_id":      createResult.RunID,
			"status":      createResult.Status,
			"message":     fmt.Sprintf("Template workflow started with template: %s", req.TemplateID),
			"created_at":  deps.NowRFC3339(),
			"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", createResult.WorkflowID),
			"session_id":  createResult.SessionID,
		})
	}
}

func handleCreateTask(w http.ResponseWriter, r *http.Request, deps TasksDeps) {
	var req httpdto.CreateTaskHTTPBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	taskType := strings.TrimSpace(req.TaskType)
	if taskType == "" {
		taskType = ucdto.TaskTypeMain
	}
	if taskType != ucdto.TaskTypeMain && taskType != ucdto.TaskTypeCardTemplate {
		http.Error(w, "unsupported task_type", http.StatusBadRequest)
		return
	}
	query := strings.TrimSpace(req.Query)
	if query == "" {
		query = strings.TrimSpace(req.Input.Query)
	}
	req.Input.Query = query
	switch taskType {
	case ucdto.TaskTypeMain:
		if query == "" {
			http.Error(w, "query is required in input.query for main task", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.Input.Context.TemplateID) == "" {
			http.Error(w, "template_id is required in input.context.template_id for main task", http.StatusBadRequest)
			return
		}
	case ucdto.TaskTypeCardTemplate:
		if strings.TrimSpace(req.Input.TemplateID) == "" {
			http.Error(w, "template_id is required in input.template_id for card_template task", http.StatusBadRequest)
			return
		}
	}
	userID := deps.UserID(r)
	sessionID := resolveSessionID(req.Input.SessionID)
	req.Input.SessionID = sessionID
	conversationHistory := normalizeConversationHistoryFromRequest(req.Input.ConversationHistory, 24)
	if taskType == ucdto.TaskTypeMain && deps.ReadModel != nil && deps.ReadModel.Ready() {
		historyFromSession, err := buildConversationHistoryFromSession(r.Context(), deps, sessionID, userID, 24)
		if err != nil {
			log.Printf("failed to build conversation history session_id=%s user_id=%s err=%v", sessionID, userID, err)
		} else if len(historyFromSession) > 0 {
			conversationHistory = historyFromSession
		}
	}
	taskQuery := query
	if taskQuery == "" && taskType == ucdto.TaskTypeCardTemplate {
		taskQuery = fmt.Sprintf("template:%s", strings.TrimSpace(req.Input.TemplateID))
	}
	if !deps.IsTemporalEnabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.CommandService == nil {
		http.Error(w, "command service unavailable", http.StatusServiceUnavailable)
		return
	}
	workflowID := deps.NextWorkflowID(taskType)
	cmd := ucdto.CreateTaskCommand{
		TaskID:    workflowID,
		UserID:    userID,
		TaskType:  taskType,
		SessionID: sessionID,
		Query:     taskQuery,
		Input: ucdto.CreateTaskInput{
			SessionID:           req.Input.SessionID,
			Query:               req.Input.Query,
			ConversationHistory: conversationHistory,
			Context:             ucdto.TemplateContext{TemplateID: req.Input.Context.TemplateID, TemplateVersion: req.Input.Context.TemplateVersion, TemplateProfile: req.Input.Context.TemplateProfile},
			FileIDs:             req.Input.FileIDs,
			TargetCount:         req.Input.TargetCount,
			DifficultyLevel:     req.Input.DifficultyLevel,
			TemplateID:          req.Input.TemplateID,
			Variables:           req.Input.Variables,
		},
		Config: ucdto.CreateTaskConfig{ActivityTaskQueue: req.Config.ActivityTaskQueue},
		Metadata: ucdto.CreateTaskMetadata{
			RequestID: req.Metadata.RequestID,
			Source:    req.Metadata.Source,
			TraceID:   req.Metadata.TraceID,
		},
	}
	createResult, activeTaskID, err := deps.CommandService.CreateTaskInSession(r.Context(), cmd)
	if err != nil {
		if errors.Is(err, usecase.ErrActiveTaskExists) {
			details := map[string]any{"session_id": sessionID}
			if strings.TrimSpace(activeTaskID) != "" {
				details["active_task_id"] = activeTaskID
			}
			deps.WriteAPIError(w, http.StatusConflict, deps.ActiveTaskCode, "session already has an active task", details)
			return
		}
		log.Printf("create task command failed session_id=%s user_id=%s task_id=%s err=%v", sessionID, userID, workflowID, err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	attachments := normalizeInputAttachments(req.Input.Attachments)
	if len(attachments) > 0 {
		payloadBytes, err := json.Marshal(map[string]any{
			"attachments": attachments,
			"file_ids":    req.Input.FileIDs,
		})
		if err != nil {
			log.Printf("failed to marshal attachment payload session_id=%s user_id=%s task_id=%s err=%v", createResult.SessionID, userID, workflowID, err)
		} else if err := deps.ReadModel.InsertEvent(
			r.Context(),
			createResult.SessionID,
			workflowID,
			workflowID,
			"MESSAGE_SENT",
			"User message sent",
			string(payloadBytes),
			fmt.Sprintf("message:user:%s", workflowID),
			time.Now().UTC(),
		); err != nil {
			log.Printf("failed to persist user attachment metadata session_id=%s user_id=%s task_id=%s err=%v", createResult.SessionID, userID, workflowID, err)
		}
	}
	deps.EnsureWorkflowStreamReader(workflowID)
	deps.WriteJSON(w, http.StatusCreated, map[string]any{
		"workflow_id": createResult.WorkflowID,
		"run_id":      createResult.RunID,
		"status":      createResult.Status,
		"message":     "Task created and workflow started successfully",
		"created_at":  deps.NowRFC3339(),
		"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", createResult.WorkflowID),
		"session_id":  createResult.SessionID,
	})
}

func normalizeConversationHistoryFromRequest(messages []httpdto.ConversationMessage, maxMessages int) []ucdto.ConversationMessage {
	if maxMessages <= 0 {
		maxMessages = 24
	}
	normalized := make([]ucdto.ConversationMessage, 0, len(messages))
	for _, msg := range messages {
		role := strings.ToLower(strings.TrimSpace(msg.Role))
		if role != "user" && role != "assistant" && role != "system" {
			continue
		}
		content := strings.TrimSpace(msg.Content)
		if content == "" {
			continue
		}
		normalized = append(normalized, ucdto.ConversationMessage{
			Role:      role,
			Content:   content,
			Timestamp: strings.TrimSpace(msg.Timestamp),
			TaskID:    strings.TrimSpace(msg.TaskID),
		})
	}
	if len(normalized) > maxMessages {
		normalized = normalized[len(normalized)-maxMessages:]
	}
	return normalized
}

func buildConversationHistoryFromSession(ctx context.Context, deps TasksDeps, sessionID, userID string, maxMessages int) ([]ucdto.ConversationMessage, error) {
	if maxMessages <= 0 {
		maxMessages = 24
	}
	tasks, err := deps.ReadModel.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	if len(tasks) == 0 {
		return nil, nil
	}
	events, err := deps.ReadModel.ListSessionEvents(ctx, sessionID, 2000, 0)
	if err != nil {
		return nil, err
	}
	eventsByTask := make(map[string][]usecase.EventRow)
	for _, ev := range events {
		taskID := ""
		if ev.TaskID != nil {
			taskID = *ev.TaskID
		}
		eventsByTask[taskID] = append(eventsByTask[taskID], ev)
	}

	messages := make([]ucdto.ConversationMessage, 0, len(tasks)*2)
	for _, t := range tasks {
		taskID := strings.TrimSpace(t.TaskID)
		query := strings.TrimSpace(valueFromPtr(t.Query))
		timestamp := taskTimestampRFC3339(t.StartedAt, t.CompletedAt)
		if query != "" {
			messages = append(messages, ucdto.ConversationMessage{
				Role:      "user",
				Content:   query,
				Timestamp: timestamp,
				TaskID:    taskID,
			})
		}

		assistantContent := strings.TrimSpace(ExtractResultMessage(t.Result))
		if assistantContent == "" {
			if text, ts := extractAssistantContentFromEvents(eventsByTask[taskID]); strings.TrimSpace(text) != "" {
				assistantContent = strings.TrimSpace(text)
				if !ts.IsZero() {
					timestamp = ts.UTC().Format(time.RFC3339)
				}
			}
		}
		if assistantContent != "" {
			messages = append(messages, ucdto.ConversationMessage{
				Role:      "assistant",
				Content:   assistantContent,
				Timestamp: timestamp,
				TaskID:    taskID,
			})
			continue
		}
		if strings.EqualFold(valueFromPtr(t.Status), "cancelled") {
			messages = append(messages, ucdto.ConversationMessage{
				Role:      "assistant",
				Content:   "This task was cancelled.",
				Timestamp: timestamp,
				TaskID:    taskID,
			})
		}
	}

	if len(messages) > maxMessages {
		messages = messages[len(messages)-maxMessages:]
	}
	return messages, nil
}

func taskTimestampRFC3339(startedAt, completedAt *time.Time) string {
	if startedAt != nil {
		return startedAt.UTC().Format(time.RFC3339)
	}
	if completedAt != nil {
		return completedAt.UTC().Format(time.RFC3339)
	}
	return ""
}

func handleListTasks(w http.ResponseWriter, r *http.Request, deps TasksDeps) {
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
	userID := deps.UserID(r)
	items, total, err := deps.TaskService.ListTasks(r.Context(), usecase.ListTasksInput{UserID: userID, Limit: limit, Offset: offset})
	if err != nil {
		http.Error(w, "failed to list tasks", http.StatusInternalServerError)
		return
	}
	taskIDs := make([]string, 0, len(items))
	for _, t := range items {
		taskIDs = append(taskIDs, t.ID().String())
	}
	usageByTask := map[string]usecase.TaskUsageSummary{}
	if deps.ReadModel != nil && len(taskIDs) > 0 {
		usageByTask, err = deps.ReadModel.GetTaskUsageSummaryMapByTaskIDs(r.Context(), userID, taskIDs)
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
			"status":      v1support.MapTaskStatus(t),
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
	deps.WriteJSON(w, http.StatusOK, map[string]any{"tasks": tasks, "total_count": total})
}

func handleGetTask(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	userID := deps.UserID(r)
	if !deps.AuthorizeTaskAccess(r, userID, taskID) {
		deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for task resource", map[string]any{"task_id": taskID})
		return
	}
	if deps.WorkflowSvc == nil || !deps.WorkflowSvc.Enabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	desc, err := deps.WorkflowSvc.DescribeWorkflow(r.Context(), taskID, "")
	if err != nil {
		http.Error(w, "task not found", http.StatusNotFound)
		return
	}
	sessionID := ""
	if sid, err := deps.WorkflowSvc.ResolveTaskSession(r.Context(), taskID); err == nil {
		sessionID = sid
	}
	response := map[string]any{
		"workflow_id": taskID,
		"task_id":     taskID,
		"task_type":   "main",
		"query":       "",
		"status":      desc.Status,
		"created_at":  desc.StartTime.UTC().Format(time.RFC3339),
		"session_id":  sessionID,
		"metadata": map[string]any{
			"task_context": map[string]any{},
		},
	}
	if desc.CloseTime != nil {
		response["finished_at"] = desc.CloseTime.UTC().Format(time.RFC3339)
	}
	if desc.Status == "TASK_STATUS_COMPLETED" {
		if result, err := deps.WorkflowSvc.GetWorkflowResult(r.Context(), taskID, desc.RunID); err == nil {
			response["result"] = result
		}
	}
	deps.WriteJSON(w, http.StatusOK, response)
}

func handleTaskControl(w http.ResponseWriter, r *http.Request, taskID string, action string, deps TasksDeps) {
	userID := deps.UserID(r)
	if !deps.AuthorizeTaskAccess(r, userID, taskID) {
		deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for task resource", map[string]any{"task_id": taskID})
		return
	}
	if action == "control-state" {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleTaskControlState(w, r, taskID, deps)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if strings.TrimSpace(r.Header.Get("Idempotency-Key")) == "" {
		deps.WriteAPIError(w, http.StatusBadRequest, deps.IdempotencyRequiredCode, "Idempotency-Key header is required", map[string]any{"task_id": taskID, "action": action})
		return
	}
	var req struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&req)
	if deps.WorkflowSvc == nil || !deps.WorkflowSvc.Enabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	err := deps.WorkflowSvc.ApplyTaskAction(r.Context(), taskID, action, req.Reason, userID)
	if errors.Is(err, usecase.ErrInvalidTransition) {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err != nil {
		deps.WriteJSON(w, http.StatusBadRequest, map[string]any{"success": false, "message": err.Error(), "workflow_id": taskID})
		return
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"success":     true,
		"message":     fmt.Sprintf("Task %s signal sent successfully", action),
		"workflow_id": taskID,
	})
}

func handleTaskControlState(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	if deps.WorkflowSvc == nil || !deps.WorkflowSvc.Enabled() {
		http.Error(w, "temporal not enabled", http.StatusServiceUnavailable)
		return
	}
	isPaused := false
	isCancelled := false
	pausedAt := ""
	pauseReason := ""
	cancelReason := ""
	st, err := deps.WorkflowSvc.QueryControlState(r.Context(), taskID)
	if err == nil && st != nil {
		isPaused = st.IsPaused
		isCancelled = st.IsCancelled
		if st.PausedAt != nil {
			pausedAt = st.PausedAt.UTC().Format(time.RFC3339)
		}
		pauseReason = st.PauseReason
		cancelReason = st.CancelReason
	}
	userID := deps.UserID(r)
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"is_paused":     isPaused,
		"is_cancelled":  isCancelled,
		"paused_at":     pausedAt,
		"pause_reason":  pauseReason,
		"paused_by":     userID,
		"cancel_reason": cancelReason,
		"cancelled_by":  userID,
	})
}

func resolveSessionID(raw string) string {
	sessionID := strings.TrimSpace(raw)
	if sessionID != "" {
		return sessionID
	}
	return fmt.Sprintf("session_%d", time.Now().UTC().UnixNano())
}

func normalizeInputAttachments(raw []httpdto.Attachment) []map[string]any {
	if len(raw) == 0 {
		return nil
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		fileID := strings.TrimSpace(item.FileID)
		filename := strings.TrimSpace(item.Filename)
		if fileID == "" || filename == "" {
			continue
		}
		size := item.Size
		if size < 0 {
			size = 0
		}
		mimeType := strings.TrimSpace(item.MimeType)
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
