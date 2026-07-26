package v1

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"

	"task-orchestrator/internal/usecase"
)

func NewTemplateTasksHandler(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method == http.MethodGet {
			if deps.TemplateService == nil {
				http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
				return
			}
			userID := deps.UserID(r)
			result, err := deps.TemplateService.ListTemplates(r.Context(), userID, 100, 0)
			if err != nil {
				http.Error(w, "failed to list templates", http.StatusInternalServerError)
				return
			}
			templates := make([]map[string]any, 0, len(result.Templates))
			for _, row := range result.Templates {
				templates = append(templates, map[string]any{
					"id":          row.TemplateID,
					"name":        row.Name,
					"description": row.Description,
					"version":     row.LatestVersion,
					"category":    "general",
					"tags":        row.Tags,
				})
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{"templates": templates, "total_count": result.TotalCount})
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			TemplateID string           `json:"template_id"`
			Variables  map[string]any   `json:"variables"`
			SessionID  string           `json:"session_id"`
			Config     CreateTaskConfig `json:"config"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.TemplateID) == "" {
			http.Error(w, "template_id is required", http.StatusBadRequest)
			return
		}
		if !deps.IsTaskExecutionAvailable() {
			http.Error(w, "task execution unavailable", http.StatusServiceUnavailable)
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
		correlationID, err := ensureCorrelationID("")
		if err != nil {
			http.Error(w, "failed to generate correlation_id", http.StatusInternalServerError)
			return
		}
		workflowID := deps.NextWorkflowID(usecase.TaskTypeCardTemplate)
		cmd := usecase.CreateTaskCommand{
			TaskID:    workflowID,
			UserID:    userID,
			TaskType:  usecase.TaskTypeCardTemplate,
			SessionID: sessionID,
			Query:     fmt.Sprintf("template:%s", strings.TrimSpace(req.TemplateID)),
			Input: usecase.AgentTaskInput{
				SessionID:  sessionID,
				TemplateID: req.TemplateID,
				Variables:  req.Variables,
				ContextEnvelope: map[string]any{
					"correlation_id": correlationID,
				},
			},
			Config: usecase.CreateTaskConfig{ModelRef: strings.TrimSpace(firstNonEmptyStringAny(req.Config.ModelRef, deps.DefaultModelRef))},
			Metadata: usecase.CreateTaskMetadata{
				RequestID: correlationID,
				Source:    "tasks/template",
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
		deps.WriteJSON(w, http.StatusCreated, map[string]any{
			"workflow_id":    createResult.WorkflowID,
			"run_id":         createResult.RunID,
			"process_id":     createResult.ProcessID,
			"user_message":   createResult.UserMessage,
			"cursor":         createResult.Cursor,
			"status":         createResult.Status,
			"message":        fmt.Sprintf("Template workflow started with template: %s", req.TemplateID),
			"created_at":     deps.NowRFC3339(),
			"stream_url":     fmt.Sprintf("/api/v1/sessions/%s/events?after=%d", createResult.SessionID, createResult.Cursor),
			"session_id":     createResult.SessionID,
			"correlation_id": correlationID,
		})
	}
}

func handleCreateTask(w http.ResponseWriter, r *http.Request, deps TasksDeps) {
	var req CreateTaskHTTPBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	taskType := strings.TrimSpace(req.TaskType)
	if taskType == "" {
		taskType = usecase.TaskTypeMain
	}
	if taskType != usecase.TaskTypeMain && taskType != usecase.TaskTypeCardTemplate {
		http.Error(w, "unsupported task_type", http.StatusBadRequest)
		return
	}
	query := strings.TrimSpace(req.Query)
	if query == "" {
		query = strings.TrimSpace(req.Input.Query)
	}
	req.Input.Query = query
	userID := deps.UserID(r)
	switch taskType {
	case usecase.TaskTypeMain:
		if query == "" {
			http.Error(w, "query is required in input.query for main task", http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.Input.Context.TemplateID) == "" && deps.TemplateService != nil {
			if resolved, err := deps.TemplateService.GetDefaultTemplate(r.Context(), userID); err == nil && strings.TrimSpace(resolved.TemplateID) != "" {
				req.Input.Context.TemplateID = strings.TrimSpace(resolved.TemplateID)
				if req.Input.Context.TemplateVersion <= 0 {
					req.Input.Context.TemplateVersion = resolved.Version
				}
			}
			if strings.TrimSpace(req.Input.Context.TemplateID) == "" {
				http.Error(w, "template_id is required in input.context.template_id for main task (or configure a default template)", http.StatusBadRequest)
				return
			}
		}
	case usecase.TaskTypeCardTemplate:
		if strings.TrimSpace(req.Input.TemplateID) == "" {
			http.Error(w, "template_id is required in input.template_id for card_template task", http.StatusBadRequest)
			return
		}
	}
	sessionID := resolveSessionID(req.Input.SessionID)
	req.Input.SessionID = sessionID
	taskQuery := query
	if taskQuery == "" && taskType == usecase.TaskTypeCardTemplate {
		taskQuery = fmt.Sprintf("template:%s", strings.TrimSpace(req.Input.TemplateID))
	}
	if !deps.IsTaskExecutionAvailable() {
		http.Error(w, "task execution unavailable", http.StatusServiceUnavailable)
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
	if deps.TaskPreparation == nil {
		http.Error(w, "task input preparation unavailable", http.StatusServiceUnavailable)
		return
	}
	correlationID, err := ensureCorrelationID(req.Metadata.RequestID)
	if err != nil {
		http.Error(w, "failed to generate correlation_id", http.StatusInternalServerError)
		return
	}
	req.Metadata.RequestID = correlationID
	workflowID := deps.NextWorkflowID(taskType)
	prepared, err := deps.TaskPreparation.PrepareTaskInput(r.Context(), usecase.TaskInputPreparationRequest{
		TaskID: workflowID, TaskType: taskType, UserID: userID, SessionID: sessionID, CorrelationID: correlationID,
		Input: usecase.AgentTaskInput{
			SessionID: sessionID, Query: req.Input.Query, ConversationHistory: req.Input.ConversationHistory,
			Context:    usecase.TemplateContext{TemplateID: req.Input.Context.TemplateID, TemplateVersion: req.Input.Context.TemplateVersion, TemplateProfile: req.Input.Context.TemplateProfile},
			FilePolicy: req.Input.FilePolicy, ContextEnvelope: req.Input.ContextEnvelope, FileIDs: req.Input.FileIDs,
			TargetCount: req.Input.TargetCount, DifficultyLevel: req.Input.DifficultyLevel, TemplateID: req.Input.TemplateID, Variables: req.Input.Variables,
		},
		Attachments: taskPreparationAttachments(req.Input.Attachments),
	})
	if err != nil {
		log.Printf("prepare task input failed session_id=%s user_id=%s task_id=%s err=%v", sessionID, userID, workflowID, err)
		http.Error(w, "failed to prepare task input", http.StatusInternalServerError)
		return
	}
	cmd := usecase.CreateTaskCommand{
		TaskID:      workflowID,
		UserID:      userID,
		TaskType:    taskType,
		SessionID:   sessionID,
		Query:       taskQuery,
		Input:       prepared.Input,
		Attachments: taskPreparationAttachments(req.Input.Attachments),
		Config: usecase.CreateTaskConfig{
			ActivityTaskQueue: req.Config.ActivityTaskQueue,
			ModelRef:          strings.TrimSpace(firstNonEmptyStringAny(req.Config.ModelRef, deps.DefaultModelRef)),
		},
		Metadata: usecase.CreateTaskMetadata{
			RequestID: correlationID,
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
	if len(prepared.SessionEvents) > 0 {
		if err := deps.CommandService.RecordSessionEvents(r.Context(), prepared.SessionEvents); err != nil {
			log.Printf("record task preparation events session_id=%s user_id=%s task_id=%s err=%v", createResult.SessionID, userID, workflowID, err)
		}
	}
	deps.WriteJSON(w, http.StatusCreated, map[string]any{
		"workflow_id":    createResult.WorkflowID,
		"run_id":         createResult.RunID,
		"process_id":     createResult.ProcessID,
		"user_message":   createResult.UserMessage,
		"cursor":         createResult.Cursor,
		"status":         createResult.Status,
		"message":        "Task created and workflow started successfully",
		"created_at":     deps.NowRFC3339(),
		"stream_url":     fmt.Sprintf("/api/v1/sessions/%s/events?after=%d", createResult.SessionID, createResult.Cursor),
		"session_id":     createResult.SessionID,
		"correlation_id": correlationID,
		"file_ids":       prepared.EffectiveFileIDs,
	})
}

func taskPreparationAttachments(attachments []Attachment) []usecase.FileAttachment {
	prepared := make([]usecase.FileAttachment, 0, len(attachments))
	for _, attachment := range attachments {
		prepared = append(prepared, usecase.FileAttachment{FileID: attachment.FileID, Filename: attachment.Filename, Size: attachment.Size, MimeType: attachment.MimeType})
	}
	return prepared
}
