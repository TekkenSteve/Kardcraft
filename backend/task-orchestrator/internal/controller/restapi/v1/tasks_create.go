package v1

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

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
		deps.EnsureWorkflowStreamReader(createResult.WorkflowID)
		deps.WriteJSON(w, http.StatusCreated, map[string]any{
			"workflow_id":    createResult.WorkflowID,
			"run_id":         createResult.RunID,
			"status":         createResult.Status,
			"message":        fmt.Sprintf("Template workflow started with template: %s", req.TemplateID),
			"created_at":     deps.NowRFC3339(),
			"stream_url":     fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", createResult.WorkflowID),
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
		if strings.TrimSpace(req.Input.Context.TemplateID) == "" {
			if deps.ReadModel != nil && deps.ReadModel.Ready() {
				if resolved, err := deps.ReadModel.GetResolvedDefaultTemplate(r.Context(), userID); err == nil && resolved != nil && strings.TrimSpace(resolved.DefaultTemplateID) != "" {
					req.Input.Context.TemplateID = strings.TrimSpace(resolved.DefaultTemplateID)
					if req.Input.Context.TemplateVersion <= 0 {
						req.Input.Context.TemplateVersion = resolved.DefaultTemplateVersion
					}
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
	req.Input.FilePolicy = normalizeFilePolicy(req.Input.FilePolicy)
	conversationHistory := normalizeConversationHistoryFromRequest(req.Input.ConversationHistory, 24)
	if taskType == usecase.TaskTypeMain && deps.ReadModel != nil && deps.ReadModel.Ready() {
		historyFromSession, err := buildConversationHistoryFromSession(r.Context(), deps, sessionID, userID, 24)
		if err != nil {
			log.Printf("failed to build conversation history session_id=%s user_id=%s err=%v", sessionID, userID, err)
		} else if len(historyFromSession) > 0 {
			conversationHistory = historyFromSession
		}
	}
	taskQuery := query
	if taskQuery == "" && taskType == usecase.TaskTypeCardTemplate {
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
	explicitFileIDs := append([]string(nil), req.Input.FileIDs...)
	effectiveFileIDs := append([]string(nil), explicitFileIDs...)
	sessionFileArtifacts := []map[string]any{}
	inheritedFileIDs := []string{}
	if req.Input.FilePolicy != "explicit_only" {
		artifacts, resolved, err := resolveSessionFileContext(r.Context(), deps, sessionID)
		if err != nil {
			log.Printf("failed to resolve inherited file_ids session_id=%s user_id=%s err=%v", sessionID, userID, err)
		} else {
			sessionFileArtifacts = artifacts
			inheritedFileIDs = resolved
		}
	}
	effectiveFileIDs = applyFilePolicy(req.Input.FilePolicy, inheritedFileIDs, effectiveFileIDs)
	req.Input.EffectiveFileIDs = append([]string(nil), effectiveFileIDs...)
	req.Input.FileIDs = append([]string(nil), effectiveFileIDs...)
	req.Input.ContextEnvelope = buildContextEnvelope(
		r.Context(),
		deps,
		userID,
		sessionID,
		req.Input.Query,
		req.Input.FilePolicy,
		req.Input.ContextEnvelope,
		conversationHistory,
		sessionFileArtifacts,
		explicitFileIDs,
		inheritedFileIDs,
		effectiveFileIDs,
	)
	correlationID, err := ensureCorrelationID(req.Metadata.RequestID)
	if err != nil {
		http.Error(w, "failed to generate correlation_id", http.StatusInternalServerError)
		return
	}
	req.Metadata.RequestID = correlationID
	req.Input.ContextEnvelope["correlation_id"] = correlationID

	workflowID := deps.NextWorkflowID(taskType)
	cmd := usecase.CreateTaskCommand{
		TaskID:    workflowID,
		UserID:    userID,
		TaskType:  taskType,
		SessionID: sessionID,
		Query:     taskQuery,
		Input: usecase.AgentTaskInput{
			SessionID:           req.Input.SessionID,
			Query:               req.Input.Query,
			ConversationHistory: conversationHistory,
			Context:             usecase.TemplateContext{TemplateID: req.Input.Context.TemplateID, TemplateVersion: req.Input.Context.TemplateVersion, TemplateProfile: req.Input.Context.TemplateProfile},
			FilePolicy:          req.Input.FilePolicy,
			ContextEnvelope:     req.Input.ContextEnvelope,
			FileIDs:             req.Input.FileIDs,
			EffectiveFileIDs:    req.Input.EffectiveFileIDs,
			TargetCount:         req.Input.TargetCount,
			DifficultyLevel:     req.Input.DifficultyLevel,
			TemplateID:          req.Input.TemplateID,
			Variables:           req.Input.Variables,
		},
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
	persistWorkspaceLifecycleAuditEvent(
		r.Context(),
		deps,
		createResult.SessionID,
		workflowID,
		userID,
		req.Input.ContextEnvelope,
	)
	if deps.BindWorkflowRunID != nil {
		deps.BindWorkflowRunID(createResult.WorkflowID, createResult.RunID)
	}
	persistPlannerTraceEvents(
		r.Context(),
		deps,
		createResult.SessionID,
		workflowID,
		workflowID,
		buildPlannerTraceRecords(req.Input.FilePolicy, explicitFileIDs, inheritedFileIDs, effectiveFileIDs, req.Input.ContextEnvelope, len(conversationHistory)),
	)
	attachments := normalizeInputAttachments(req.Input.Attachments)
	if len(attachments) > 0 {
		payloadBytes, err := json.Marshal(map[string]any{
			"attachments": attachments,
			"file_ids":    effectiveFileIDs,
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
		"workflow_id":    createResult.WorkflowID,
		"run_id":         createResult.RunID,
		"status":         createResult.Status,
		"message":        "Task created and workflow started successfully",
		"created_at":     deps.NowRFC3339(),
		"stream_url":     fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", createResult.WorkflowID),
		"session_id":     createResult.SessionID,
		"correlation_id": correlationID,
		"file_ids":       effectiveFileIDs,
	})
}
