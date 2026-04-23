package handlers

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
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

const (
	workspaceIdleThreshold = 6 * time.Hour
	workspaceTTLThreshold  = 72 * time.Hour
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

	ActiveTaskCode          string
	AuthzDeniedCode         string
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
	userID := deps.UserID(r)
	switch taskType {
	case ucdto.TaskTypeMain:
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
	case ucdto.TaskTypeCardTemplate:
		if strings.TrimSpace(req.Input.TemplateID) == "" {
			http.Error(w, "template_id is required in input.template_id for card_template task", http.StatusBadRequest)
			return
		}
	}
	sessionID := resolveSessionID(req.Input.SessionID)
	req.Input.SessionID = sessionID
	req.Input.FilePolicy = normalizeFilePolicy(req.Input.FilePolicy)
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
			FilePolicy:          req.Input.FilePolicy,
			ContextEnvelope:     req.Input.ContextEnvelope,
			FileIDs:             req.Input.FileIDs,
			EffectiveFileIDs:    req.Input.EffectiveFileIDs,
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
	persistWorkspaceLifecycleAuditEvent(
		r.Context(),
		deps,
		createResult.SessionID,
		workflowID,
		userID,
		req.Input.ContextEnvelope,
	)
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
		"workflow_id": createResult.WorkflowID,
		"run_id":      createResult.RunID,
		"status":      createResult.Status,
		"message":     "Task created and workflow started successfully",
		"created_at":  deps.NowRFC3339(),
		"stream_url":  fmt.Sprintf("/api/v1/stream/sse?workflow_id=%s", createResult.WorkflowID),
		"session_id":  createResult.SessionID,
		"file_ids":    effectiveFileIDs,
	})
}

func normalizeFilePolicy(raw string) string {
	policy := strings.ToLower(strings.TrimSpace(raw))
	switch policy {
	case "", "inherit":
		return "inherit"
	case "explicit_only", "exclude":
		return policy
	default:
		return "inherit"
	}
}

func applyFilePolicy(policy string, inheritedFileIDs, explicitFileIDs []string) []string {
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)

	switch policy {
	case "explicit_only":
		return normalizedExplicit
	case "exclude":
		excluded := make(map[string]struct{}, len(normalizedExplicit))
		for _, fileID := range normalizedExplicit {
			excluded[fileID] = struct{}{}
		}
		out := make([]string, 0, len(normalizedInherited))
		for _, fileID := range normalizedInherited {
			if _, deny := excluded[fileID]; deny {
				continue
			}
			out = append(out, fileID)
		}
		return out
	case "inherit":
		fallthrough
	default:
		out := make([]string, 0, len(normalizedExplicit)+len(normalizedInherited))
		seen := make(map[string]struct{}, len(normalizedExplicit)+len(normalizedInherited))
		for _, fileID := range normalizedExplicit {
			if _, ok := seen[fileID]; ok {
				continue
			}
			seen[fileID] = struct{}{}
			out = append(out, fileID)
		}
		for _, fileID := range normalizedInherited {
			if _, ok := seen[fileID]; ok {
				continue
			}
			seen[fileID] = struct{}{}
			out = append(out, fileID)
		}
		return out
	}
}

func dedupeNonEmptyStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		v := strings.TrimSpace(value)
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func buildContextEnvelope(
	ctx context.Context,
	deps TasksDeps,
	userID string,
	sessionID string,
	query string,
	filePolicy string,
	base map[string]any,
	conversationHistory []ucdto.ConversationMessage,
	sessionFileArtifacts []map[string]any,
	explicitFileIDs []string,
	inheritedFileIDs []string,
	effectiveFileIDs []string,
) map[string]any {
	envelope := map[string]any{}
	for key, value := range base {
		envelope[key] = value
	}
	envelope["schema_version"] = "context-envelope.v1"

	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedEffective := dedupeNonEmptyStrings(effectiveFileIDs)
	policy := normalizeFilePolicy(filePolicy)

	envelope["request"] = map[string]any{
		"session_id":   sessionID,
		"user_id":      userID,
		"user_message": strings.TrimSpace(query),
		"intent_hint":  "",
	}

	recentMessages := make([]map[string]any, 0, minInt(8, len(conversationHistory)))
	start := 0
	if len(conversationHistory) > 8 {
		start = len(conversationHistory) - 8
	}
	for _, msg := range conversationHistory[start:] {
		recentMessages = append(recentMessages, map[string]any{
			"role":      msg.Role,
			"content":   msg.Content,
			"timestamp": msg.Timestamp,
			"task_id":   msg.TaskID,
		})
	}
	envelope["history"] = map[string]any{
		"message_count":      len(conversationHistory),
		"recent_turn_window": 8,
		"messages":           recentMessages,
		"summary":            "",
	}

	workspaceSummary := map[string]any{"available": false}
	cardsSummary := map[string]any{
		"latest_cards": []map[string]any{},
		"card_summary": "",
	}
	knowledgeState := map[string]any{
		"rag_workspace_id":   sessionID,
		"workspace_recycled": false,
		"last_query_status":  "unknown",
		"last_query_reason":  "",
	}
	if deps.ReadModel != nil && deps.ReadModel.Ready() {
		workspace, err := deps.ReadModel.LoadWorkspace(ctx, sessionID)
		if err == nil && workspace != nil {
			workspaceSummary["available"] = true
			if status := strings.TrimSpace(asStringAny(workspace["status"])); status != "" {
				workspaceSummary["status"] = status
				if status == "recycled" {
					knowledgeState["workspace_recycled"] = true
				}
			}
			lifecycleState, updatedAt, ageHours := deriveWorkspaceLifecycleState(workspace, time.Now().UTC())
			workspaceSummary["lifecycle_state"] = lifecycleState
			if updatedAt != "" {
				workspaceSummary["updated_at"] = updatedAt
			}
			workspaceSummary["age_hours"] = ageHours
			workspaceSummary["ttl_policy"] = map[string]any{
				"idle_threshold_hours": int(workspaceIdleThreshold.Hours()),
				"ttl_threshold_hours":  int(workspaceTTLThreshold.Hours()),
			}
			if lifecycleState == "recycled" {
				knowledgeState["workspace_recycled"] = true
			}
			if lifecycleState == "ttl_expired" {
				knowledgeState["last_query_reason"] = "workspace_ttl_expired"
			}
			if version := asInt64Any(workspace["version"]); version > 0 {
				workspaceSummary["version"] = version
			}
			if cards, ok := workspace["cards"].([]any); ok {
				workspaceSummary["card_count"] = len(cards)
				sampledCards := make([]map[string]any, 0, minInt(5, len(cards)))
				for _, card := range cards {
					cardMap, ok := card.(map[string]any)
					if !ok {
						continue
					}
					sampledCards = append(sampledCards, map[string]any{
						"id":    strings.TrimSpace(asStringAny(cardMap["id"])),
						"title": strings.TrimSpace(asStringAny(cardMap["title"])),
						"type":  strings.TrimSpace(asStringAny(cardMap["type"])),
					})
					if len(sampledCards) >= 5 {
						break
					}
				}
				cardsSummary["latest_cards"] = sampledCards
				cardsSummary["card_summary"] = fmt.Sprintf("%d cards in session workspace", len(cards))
			}
		}
	}

	envelope["artifacts"] = map[string]any{
		"files":              sessionFileArtifacts,
		"cards":              cardsSummary,
		"explicit_file_ids":  normalizedExplicit,
		"inherited_file_ids": normalizedInherited,
		"effective_file_ids": normalizedEffective,
		"workspace":          workspaceSummary,
	}

	envelope["knowledge_state"] = knowledgeState
	envelope["tool_capabilities"] = []string{
		"list_history_files",
		"search_ragix",
		"fetch_file_excerpt",
		"index_file_to_ragix",
		"list_history_cards",
	}
	envelope["policy"] = map[string]any{
		"disclosure_mode":             "progressive",
		"max_new_file_fetch_per_turn": 3,
		"max_excerpt_chars_per_turn":  16000,
	}

	envelope["file_resolution"] = map[string]any{
		"policy":               policy,
		"inherited_file_ids":   normalizedInherited,
		"explicit_file_ids":    normalizedExplicit,
		"effective_file_ids":   normalizedEffective,
		"effective_file_count": len(normalizedEffective),
	}
	return enforceContextEnvelopeSchema(envelope)
}

func deriveWorkspaceLifecycleState(workspace map[string]any, now time.Time) (string, string, float64) {
	if workspace == nil {
		return "idle", "", 0
	}
	status := strings.ToLower(strings.TrimSpace(asStringAny(workspace["status"])))
	if status == "recycled" {
		return "recycled", strings.TrimSpace(asStringAny(workspace["updated_at"])), 0
	}

	updatedAtRaw := strings.TrimSpace(asStringAny(workspace["updated_at"]))
	if updatedAtRaw == "" {
		if status == "active" {
			return "active", "", 0
		}
		return "idle", "", 0
	}
	updatedAt, err := time.Parse(time.RFC3339, updatedAtRaw)
	if err != nil {
		if status == "active" {
			return "active", updatedAtRaw, 0
		}
		return "idle", updatedAtRaw, 0
	}

	age := now.Sub(updatedAt.UTC())
	if age < 0 {
		age = 0
	}
	ageHours := float64(int(age.Hours()*100)) / 100.0
	switch {
	case age >= workspaceTTLThreshold:
		return "ttl_expired", updatedAt.UTC().Format(time.RFC3339), ageHours
	case age >= workspaceIdleThreshold:
		return "idle", updatedAt.UTC().Format(time.RFC3339), ageHours
	default:
		return "active", updatedAt.UTC().Format(time.RFC3339), ageHours
	}
}

func enforceContextEnvelopeSchema(envelope map[string]any) map[string]any {
	if envelope == nil {
		envelope = map[string]any{}
	}
	schemaVersion := strings.TrimSpace(asStringAny(envelope["schema_version"]))
	if schemaVersion == "" {
		schemaVersion = "context-envelope.v1"
	}
	envelope["schema_version"] = schemaVersion

	ensureMap := func(key string) map[string]any {
		raw, ok := envelope[key]
		if !ok {
			m := map[string]any{}
			envelope[key] = m
			return m
		}
		if m, ok := raw.(map[string]any); ok {
			return m
		}
		m := map[string]any{}
		envelope[key] = m
		return m
	}
	for _, key := range []string{"request", "history", "artifacts", "knowledge_state", "policy", "file_resolution"} {
		ensureMap(key)
	}

	compatibility := map[string]any{
		"unknown_fields_preserved": true,
		"normalization_strategy":   "best_effort",
	}
	if raw, ok := envelope["compatibility"].(map[string]any); ok {
		for k, v := range compatibility {
			if _, exists := raw[k]; !exists {
				raw[k] = v
			}
		}
		envelope["compatibility"] = raw
	} else {
		envelope["compatibility"] = compatibility
	}

	capabilities := []string{}
	switch raw := envelope["tool_capabilities"].(type) {
	case []string:
		capabilities = append(capabilities, raw...)
	case []any:
		for _, item := range raw {
			v := strings.TrimSpace(asStringAny(item))
			if v == "" {
				continue
			}
			capabilities = append(capabilities, v)
		}
	}
	if len(capabilities) == 0 {
		capabilities = []string{
			"list_history_files",
			"search_ragix",
			"fetch_file_excerpt",
			"index_file_to_ragix",
			"list_history_cards",
		}
	}
	envelope["tool_capabilities"] = dedupeNonEmptyStrings(capabilities)
	return envelope
}

type plannerTraceRecord struct {
	Action       string   `json:"action"`
	Reason       string   `json:"reason"`
	InputRef     string   `json:"input_ref"`
	Outcome      string   `json:"outcome"`
	EvidenceRefs []string `json:"evidence_refs,omitempty"`
}

func buildPlannerTraceRecords(
	filePolicy string,
	explicitFileIDs []string,
	inheritedFileIDs []string,
	effectiveFileIDs []string,
	contextEnvelope map[string]any,
	historyCount int,
) []plannerTraceRecord {
	normalizedPolicy := normalizeFilePolicy(filePolicy)
	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedEffective := dedupeNonEmptyStrings(effectiveFileIDs)
	schemaVersion := strings.TrimSpace(asStringAny(contextEnvelope["schema_version"]))
	if schemaVersion == "" {
		schemaVersion = "context-envelope.v1"
	}
	return []plannerTraceRecord{
		{
			Action:   "resolve_effective_file_ids",
			Reason:   "determine file scope for current turn",
			InputRef: fmt.Sprintf("file_policy=%s explicit=%d inherited=%d", normalizedPolicy, len(normalizedExplicit), len(normalizedInherited)),
			Outcome:  fmt.Sprintf("effective=%d", len(normalizedEffective)),
			EvidenceRefs: []string{
				fmt.Sprintf("file_policy:%s", normalizedPolicy),
				fmt.Sprintf("effective_file_ids:%d", len(normalizedEffective)),
			},
		},
		{
			Action:   "build_context_envelope",
			Reason:   "provide stable planner context with compatibility guarantees",
			InputRef: fmt.Sprintf("history_count=%d", historyCount),
			Outcome:  fmt.Sprintf("schema=%s", schemaVersion),
			EvidenceRefs: []string{
				fmt.Sprintf("context_envelope:%s", schemaVersion),
			},
		},
		{
			Action:   "progressive_disclosure_gate",
			Reason:   "prefer retrieval and targeted evidence access before clarification",
			InputRef: fmt.Sprintf("effective_file_count=%d", len(normalizedEffective)),
			Outcome:  "tool_broker_first",
			EvidenceRefs: []string{
				"policy:progressive",
			},
		},
	}
}

func persistPlannerTraceEvents(
	ctx context.Context,
	deps TasksDeps,
	sessionID string,
	taskID string,
	workflowID string,
	records []plannerTraceRecord,
) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() || len(records) == 0 {
		return
	}
	for idx, record := range records {
		payloadBytes, err := json.Marshal(map[string]any{
			"trace_version": "planner_trace.v1",
			"sequence":      idx + 1,
			"record":        record,
		})
		if err != nil {
			log.Printf("failed to marshal planner trace task_id=%s session_id=%s err=%v", taskID, sessionID, err)
			continue
		}
		streamID := fmt.Sprintf("planner_trace:%s:%03d", taskID, idx+1)
		if err := deps.ReadModel.InsertEvent(
			ctx,
			sessionID,
			taskID,
			workflowID,
			"PLANNER_TRACE",
			record.Action,
			string(payloadBytes),
			streamID,
			time.Now().UTC(),
		); err != nil {
			log.Printf("failed to persist planner trace task_id=%s session_id=%s stream_id=%s err=%v", taskID, sessionID, streamID, err)
		}
	}
}

func persistWorkspaceLifecycleAuditEvent(
	ctx context.Context,
	deps TasksDeps,
	sessionID string,
	workflowID string,
	userID string,
	contextEnvelope map[string]any,
) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		return
	}
	artifacts, ok := contextEnvelope["artifacts"].(map[string]any)
	if !ok {
		return
	}
	workspace, ok := artifacts["workspace"].(map[string]any)
	if !ok {
		return
	}
	lifecycleState := strings.TrimSpace(asStringAny(workspace["lifecycle_state"]))
	if lifecycleState == "" {
		return
	}
	payloadBytes, err := json.Marshal(map[string]any{
		"schema_version":   "workspace_lifecycle_audit.v1",
		"user_id":          userID,
		"session_id":       sessionID,
		"workspace_status": strings.TrimSpace(asStringAny(workspace["status"])),
		"lifecycle_state":  lifecycleState,
		"age_hours":        workspace["age_hours"],
		"ttl_policy":       workspace["ttl_policy"],
	})
	if err != nil {
		log.Printf("failed to marshal workspace lifecycle audit session_id=%s err=%v", sessionID, err)
		return
	}
	taskID := workflowID
	if strings.TrimSpace(taskID) == "" {
		taskID = fmt.Sprintf("task_audit_%d", time.Now().UTC().UnixNano())
	}
	rawStreamID := fmt.Sprintf("workspace_lifecycle:%s:%d", taskID, time.Now().UTC().UnixNano())
	sum := sha1.Sum([]byte(rawStreamID))
	streamID := "workspace_lifecycle:" + hex.EncodeToString(sum[:])
	if err := deps.ReadModel.InsertEvent(
		ctx,
		sessionID,
		taskID,
		taskID,
		"WORKSPACE_LIFECYCLE_EVALUATED",
		"Workspace lifecycle evaluated",
		string(payloadBytes),
		streamID,
		time.Now().UTC(),
	); err != nil {
		log.Printf("failed to persist workspace lifecycle audit session_id=%s task_id=%s err=%v", sessionID, taskID, err)
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func resolveSessionFileContext(ctx context.Context, deps TasksDeps, sessionID string) ([]map[string]any, []string, error) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		return nil, nil, nil
	}
	events, err := deps.ReadModel.ListSessionEvents(ctx, sessionID, 2000, 0)
	if err != nil {
		return nil, nil, err
	}
	if len(events) == 0 {
		return nil, nil, nil
	}
	fileIDs := make([]string, 0)
	artifacts := make([]map[string]any, 0)
	seen := make(map[string]struct{})
	for i := len(events) - 1; i >= 0; i-- {
		payload := parsePayloadText(events[i].Payload)
		record, ok := payload.(map[string]any)
		if !ok {
			continue
		}
		for _, artifact := range extractFileArtifactsFromEventPayload(record) {
			fileID := strings.TrimSpace(asStringAny(artifact["file_id"]))
			if fileID == "" {
				continue
			}
			if _, exists := seen[fileID]; exists {
				continue
			}
			seen[fileID] = struct{}{}
			fileIDs = append(fileIDs, fileID)
			artifacts = append(artifacts, artifact)
		}
	}
	if len(fileIDs) == 0 {
		return nil, nil, nil
	}
	return artifacts, fileIDs, nil
}

func extractFileArtifactsFromEventPayload(record map[string]any) []map[string]any {
	out := make([]map[string]any, 0)
	appendFromAttachments := func(value any) {
		list, ok := value.([]any)
		if !ok {
			return
		}
		for _, entry := range list {
			item, ok := entry.(map[string]any)
			if !ok {
				continue
			}
			fileID := strings.TrimSpace(asStringAny(item["file_id"]))
			if fileID == "" {
				continue
			}
			filename := strings.TrimSpace(asStringAny(item["filename"]))
			if filename == "" {
				filename = fileID
			}
			mimeType := strings.TrimSpace(asStringAny(item["mime_type"]))
			if mimeType == "" {
				mimeType = "application/octet-stream"
			}
			size := asInt64Any(item["size"])
			if size < 0 {
				size = 0
			}
			out = append(out, map[string]any{
				"file_id":            fileID,
				"filename":           filename,
				"mime_type":          mimeType,
				"size":               size,
				"status":             "active",
				"pinned":             false,
				"index_state":        "unknown",
				"workspace_presence": "unknown",
				"last_used_at":       "",
			})
		}
	}
	appendFromFileIDs := func(value any) {
		list, ok := value.([]any)
		if !ok {
			return
		}
		for _, entry := range list {
			fileID := strings.TrimSpace(asStringAny(entry))
			if fileID == "" {
				continue
			}
			out = append(out, map[string]any{
				"file_id":            fileID,
				"filename":           fileID,
				"mime_type":          "application/octet-stream",
				"size":               int64(0),
				"status":             "active",
				"pinned":             false,
				"index_state":        "unknown",
				"workspace_presence": "unknown",
				"last_used_at":       "",
			})
		}
	}

	appendFromAttachments(record["attachments"])
	appendFromFileIDs(record["file_ids"])
	if input, ok := record["input"].(map[string]any); ok {
		appendFromAttachments(input["attachments"])
		appendFromFileIDs(input["file_ids"])
	}
	if len(out) == 0 {
		return nil
	}
	deduped := make([]map[string]any, 0, len(out))
	seen := make(map[string]struct{}, len(out))
	for _, item := range out {
		fileID := strings.TrimSpace(asStringAny(item["file_id"]))
		if fileID == "" {
			continue
		}
		if _, ok := seen[fileID]; ok {
			continue
		}
		seen[fileID] = struct{}{}
		deduped = append(deduped, item)
	}
	if len(deduped) == 0 {
		return nil
	}
	return deduped
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
	if action == "planner-trace" {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleTaskPlannerTrace(w, r, taskID, deps)
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

func handleTaskPlannerTrace(w http.ResponseWriter, r *http.Request, taskID string, deps TasksDeps) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	events, err := deps.ReadModel.ListWorkflowEvents(r.Context(), taskID, 2000, 0)
	if err != nil {
		http.Error(w, "failed to load planner trace", http.StatusInternalServerError)
		return
	}
	records := make([]map[string]any, 0)
	for _, ev := range events {
		if !strings.EqualFold(strings.TrimSpace(ev.Type), "PLANNER_TRACE") {
			continue
		}
		item := map[string]any{
			"event_id":    ev.ID,
			"event_type":  ev.Type,
			"timestamp":   ev.Timestamp.UTC().Format(time.RFC3339),
			"message":     strings.TrimSpace(valueFromPtr(ev.Message)),
			"trace":       nil,
			"raw_payload": nil,
		}
		payload := parsePayloadText(ev.Payload)
		if parsed, ok := payload.(map[string]any); ok {
			item["trace"] = parsed
		} else {
			item["raw_payload"] = payload
		}
		if ev.StreamID != nil {
			item["stream_id"] = *ev.StreamID
		}
		records = append(records, item)
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"task_id":       taskID,
		"planner_trace": records,
		"total_count":   len(records),
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
