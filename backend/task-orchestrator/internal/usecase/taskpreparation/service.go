// Package taskpreparation derives Kardcraft task input from durable business
// state. It deliberately has no HTTP or GoAgent dependency.
package taskpreparation

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

const (
	maxConversationMessages = 24
	recentConversationTurns = 8
)

type Service struct {
	readModel usecase.ReadModel
	workspace usecase.Workspace
	now       func() time.Time
}

func New(readModel usecase.ReadModel, workspace usecase.Workspace) (*Service, error) {
	if readModel == nil || workspace == nil {
		return nil, fmt.Errorf("task input preparation requires read model and workspace")
	}
	return &Service{readModel: readModel, workspace: workspace, now: time.Now}, nil
}

func (s *Service) PrepareTaskInput(ctx context.Context, request usecase.TaskInputPreparationRequest) (usecase.PreparedTaskInput, error) {
	request = normalizeRequest(request)
	if request.TaskID == "" || request.UserID == "" || request.SessionID == "" || request.CorrelationID == "" {
		return usecase.PreparedTaskInput{}, fmt.Errorf("task, user, session, and correlation ids are required")
	}

	input := request.Input
	input.SessionID = request.SessionID
	input.FilePolicy = normalizeFilePolicy(input.FilePolicy)
	input.ConversationHistory = normalizeConversationHistory(input.ConversationHistory, maxConversationMessages)
	if request.TaskType == usecase.TaskTypeMain {
		if history, err := s.sessionHistory(ctx, request.SessionID, request.UserID, maxConversationMessages); err != nil {
			return usecase.PreparedTaskInput{}, fmt.Errorf("load session history: %w", err)
		} else if len(history) > 0 {
			input.ConversationHistory = history
		}
	}

	explicitFileIDs := dedupeStrings(append(append([]string(nil), input.FileIDs...), attachmentFileIDs(request.Attachments)...))
	var artifacts []map[string]any
	var inheritedFileIDs []string
	if input.FilePolicy != "explicit_only" {
		var err error
		artifacts, inheritedFileIDs, err = s.sessionFiles(ctx, request.SessionID)
		if err != nil {
			return usecase.PreparedTaskInput{}, fmt.Errorf("load session files: %w", err)
		}
	}
	effectiveFileIDs := applyFilePolicy(input.FilePolicy, inheritedFileIDs, explicitFileIDs)
	input.FileIDs = append([]string(nil), effectiveFileIDs...)
	input.EffectiveFileIDs = append([]string(nil), effectiveFileIDs...)

	workspace, err := s.workspace.DescribeWorkspace(ctx, request.SessionID, s.now().UTC())
	if err != nil {
		return usecase.PreparedTaskInput{}, fmt.Errorf("describe workspace: %w", err)
	}
	input.ContextEnvelope = buildContextEnvelope(input.ContextEnvelope, request, input, workspace, artifacts, explicitFileIDs, inheritedFileIDs, effectiveFileIDs)

	preparedAt := s.now().UTC()
	events := plannerEvents(request, input.ContextEnvelope, explicitFileIDs, inheritedFileIDs, effectiveFileIDs, preparedAt)
	if lifecycle := workspaceLifecycleEvent(request, workspace); lifecycle != nil {
		lifecycle.OccurredAt = preparedAt
		events = append(events, *lifecycle)
	}
	if event := attachmentEvent(request, effectiveFileIDs); event != nil {
		event.OccurredAt = preparedAt
		events = append(events, *event)
	}
	return usecase.PreparedTaskInput{Input: input, EffectiveFileIDs: effectiveFileIDs, SessionEvents: events}, nil
}

func normalizeRequest(request usecase.TaskInputPreparationRequest) usecase.TaskInputPreparationRequest {
	request.TaskID = strings.TrimSpace(request.TaskID)
	request.TaskType = strings.TrimSpace(request.TaskType)
	request.UserID = strings.TrimSpace(request.UserID)
	request.SessionID = strings.TrimSpace(request.SessionID)
	request.CorrelationID = strings.TrimSpace(request.CorrelationID)
	request.Input.Query = strings.TrimSpace(request.Input.Query)
	return request
}

func normalizeFilePolicy(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "explicit_only", "exclude":
		return strings.ToLower(strings.TrimSpace(value))
	default:
		return "inherit"
	}
}

func applyFilePolicy(policy string, inherited, explicit []string) []string {
	inherited = dedupeStrings(inherited)
	explicit = dedupeStrings(explicit)
	switch policy {
	case "explicit_only":
		return explicit
	case "exclude":
		excluded := make(map[string]struct{}, len(explicit))
		for _, id := range explicit {
			excluded[id] = struct{}{}
		}
		out := make([]string, 0, len(inherited))
		for _, id := range inherited {
			if _, found := excluded[id]; !found {
				out = append(out, id)
			}
		}
		return out
	default:
		return dedupeStrings(append(explicit, inherited...))
	}
}

func dedupeStrings(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		result = append(result, value)
	}
	if len(result) == 0 {
		return nil
	}
	return result
}

func (s *Service) sessionFiles(ctx context.Context, sessionID string) ([]map[string]any, []string, error) {
	events, err := s.readModel.ListSessionEvents(ctx, sessionID, 2000, 0)
	if err != nil {
		return nil, nil, err
	}
	seen := make(map[string]struct{})
	var artifacts []map[string]any
	var ids []string
	for index := len(events) - 1; index >= 0; index-- {
		for _, artifact := range eventFileArtifacts(events[index]) {
			id := stringValue(artifact["file_id"])
			if id == "" {
				continue
			}
			if _, exists := seen[id]; exists {
				continue
			}
			seen[id] = struct{}{}
			ids, artifacts = append(ids, id), append(artifacts, artifact)
		}
	}
	return artifacts, ids, nil
}

func eventFileArtifacts(event usecase.EventRow) []map[string]any {
	if event.Payload == nil || strings.TrimSpace(*event.Payload) == "" {
		return nil
	}
	var payload map[string]any
	if json.Unmarshal([]byte(*event.Payload), &payload) != nil {
		return nil
	}
	var result []map[string]any
	appendArtifacts := func(value any) {
		items, ok := value.([]any)
		if !ok {
			return
		}
		for _, item := range items {
			record, ok := item.(map[string]any)
			if !ok {
				continue
			}
			id := stringValue(record["file_id"])
			if id == "" {
				continue
			}
			filename := stringValue(record["filename"])
			if filename == "" {
				filename = id
			}
			mimeType := stringValue(record["mime_type"])
			if mimeType == "" {
				mimeType = "application/octet-stream"
			}
			result = append(result, map[string]any{"file_id": id, "filename": filename, "mime_type": mimeType, "size": int64Value(record["size"]), "status": "active", "pinned": false, "index_state": "unknown", "workspace_presence": "unknown", "last_used_at": ""})
		}
	}
	appendIDs := func(value any) {
		items, ok := value.([]any)
		if !ok {
			return
		}
		for _, item := range items {
			id := stringValue(item)
			if id == "" {
				continue
			}
			result = append(result, map[string]any{"file_id": id, "filename": id, "mime_type": "application/octet-stream", "size": int64(0), "status": "active", "pinned": false, "index_state": "unknown", "workspace_presence": "unknown", "last_used_at": ""})
		}
	}
	appendArtifacts(payload["attachments"])
	appendIDs(payload["file_ids"])
	if input, ok := payload["input"].(map[string]any); ok {
		appendArtifacts(input["attachments"])
		appendIDs(input["file_ids"])
	}
	return result
}

func (s *Service) sessionHistory(ctx context.Context, sessionID, userID string, max int) ([]usecase.AgentMessage, error) {
	tasks, err := s.readModel.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	result := make([]usecase.AgentMessage, 0, len(tasks)*2)
	for _, task := range tasks {
		if query := stringPtr(task.Query); query != "" {
			result = append(result, usecase.AgentMessage{Role: "user", Content: query})
		}
		if message := resultMessage(task.Result); message != "" {
			result = append(result, usecase.AgentMessage{Role: "assistant", Content: message})
		} else if strings.EqualFold(stringPtr(task.Status), "cancelled") {
			result = append(result, usecase.AgentMessage{Role: "assistant", Content: "This task was cancelled."})
		}
	}
	return normalizeConversationHistory(result, max), nil
}

func normalizeConversationHistory(messages []usecase.AgentMessage, max int) []usecase.AgentMessage {
	result := make([]usecase.AgentMessage, 0, len(messages))
	for _, message := range messages {
		role, content := strings.ToLower(strings.TrimSpace(message.Role)), strings.TrimSpace(message.Content)
		if (role == "user" || role == "assistant" || role == "system") && content != "" {
			result = append(result, usecase.AgentMessage{Role: role, Content: content})
		}
	}
	if len(result) > max {
		result = result[len(result)-max:]
	}
	return result
}

func resultMessage(value any) string {
	if text, ok := value.(string); ok {
		return strings.TrimSpace(text)
	}
	record, ok := value.(map[string]any)
	if !ok {
		return ""
	}
	for _, key := range []string{"message", "content", "final_output", "output", "result"} {
		if text := stringValue(record[key]); text != "" {
			return text
		}
	}
	return ""
}

func buildContextEnvelope(_ map[string]any, request usecase.TaskInputPreparationRequest, input usecase.AgentTaskInput, workspace usecase.WorkspaceContext, artifacts []map[string]any, explicit, inherited, effective []string) map[string]any {
	// The execution envelope is server-derived. Accepting arbitrary client
	// sections here would create an undocumented runtime protocol.
	envelope := make(map[string]any, 10)
	envelope["schema_version"] = "context-envelope.v1"
	envelope["correlation_id"] = request.CorrelationID
	envelope["request"] = map[string]any{"session_id": request.SessionID, "user_id": request.UserID, "user_message": input.Query, "intent_hint": ""}
	recent := input.ConversationHistory
	if len(recent) > recentConversationTurns {
		recent = recent[len(recent)-recentConversationTurns:]
	}
	messages := make([]map[string]any, 0, len(recent))
	for _, message := range recent {
		messages = append(messages, map[string]any{"role": message.Role, "content": message.Content})
	}
	envelope["history"] = map[string]any{"message_count": len(input.ConversationHistory), "recent_turn_window": recentConversationTurns, "messages": messages, "summary": ""}
	workspacePayload := map[string]any{"available": workspace.Available}
	if workspace.Available {
		workspacePayload["status"], workspacePayload["lifecycle_state"], workspacePayload["age_hours"] = workspace.Status, workspace.LifecycleState, workspace.AgeHours
		workspacePayload["ttl_policy"] = map[string]any{"idle_threshold_hours": 6, "ttl_threshold_hours": 72}
		if workspace.UpdatedAt != "" {
			workspacePayload["updated_at"] = workspace.UpdatedAt
		}
		if workspace.Version > 0 {
			workspacePayload["version"] = workspace.Version
		}
	}
	cards := make([]map[string]any, 0, len(workspace.Cards))
	for _, card := range workspace.Cards {
		cards = append(cards, map[string]any{"id": card.ID, "title": card.Title, "type": card.Type})
	}
	envelope["artifacts"] = map[string]any{"files": artifacts, "cards": map[string]any{"latest_cards": cards, "card_summary": fmt.Sprintf("%d cards in session workspace", workspace.CardCount)}, "explicit_file_ids": explicit, "inherited_file_ids": inherited, "effective_file_ids": effective, "workspace": workspacePayload}
	reason := ""
	if workspace.LifecycleState == "ttl_expired" {
		reason = "workspace_ttl_expired"
	}
	envelope["knowledge_state"] = map[string]any{"rag_workspace_id": request.SessionID, "workspace_recycled": workspace.LifecycleState == "recycled", "last_query_status": "unknown", "last_query_reason": reason}
	envelope["tool_capabilities"] = []string{"list_history_files", "search_ragix", "fetch_file_excerpt", "index_file_to_ragix", "list_history_cards"}
	envelope["policy"] = map[string]any{"disclosure_mode": "progressive", "max_new_file_fetch_per_turn": 3, "max_excerpt_chars_per_turn": 16000}
	envelope["file_resolution"] = map[string]any{"policy": input.FilePolicy, "inherited_file_ids": inherited, "explicit_file_ids": explicit, "effective_file_ids": effective, "effective_file_count": len(effective)}
	return envelope
}

func plannerEvents(request usecase.TaskInputPreparationRequest, envelope map[string]any, explicit, inherited, effective []string, occurredAt time.Time) []usecase.SessionEvent {
	records := []map[string]any{
		{"action": "resolve_effective_file_ids", "reason": "determine file scope for current turn", "input_ref": fmt.Sprintf("file_policy=%s explicit=%d inherited=%d", request.Input.FilePolicy, len(explicit), len(inherited)), "outcome": fmt.Sprintf("effective=%d", len(effective))},
		{"action": "build_context_envelope", "reason": "provide stable planner context", "input_ref": fmt.Sprintf("history_count=%d", len(request.Input.ConversationHistory)), "outcome": fmt.Sprintf("schema=%s", stringValue(envelope["schema_version"]))},
		{"action": "progressive_disclosure_gate", "reason": "prefer retrieval and targeted evidence access before clarification", "input_ref": fmt.Sprintf("effective_file_count=%d", len(effective)), "outcome": "tool_broker_first"},
	}
	events := make([]usecase.SessionEvent, 0, len(records))
	for index, record := range records {
		events = append(events, usecase.SessionEvent{SessionID: request.SessionID, TaskID: request.TaskID, WorkflowID: request.TaskID, Type: "PLANNER_TRACE", Message: record["action"].(string), Payload: map[string]any{"trace_version": "planner_trace.v1", "sequence": index + 1, "record": record}, StreamID: fmt.Sprintf("planner_trace:%s:%03d", request.TaskID, index+1), OccurredAt: occurredAt})
	}
	return events
}

func workspaceLifecycleEvent(request usecase.TaskInputPreparationRequest, workspace usecase.WorkspaceContext) *usecase.SessionEvent {
	if !workspace.Available || strings.TrimSpace(workspace.LifecycleState) == "" {
		return nil
	}
	sum := sha1.Sum([]byte("workspace_lifecycle|" + request.TaskID))
	return &usecase.SessionEvent{SessionID: request.SessionID, TaskID: request.TaskID, WorkflowID: request.TaskID, Type: "WORKSPACE_LIFECYCLE_EVALUATED", Message: "Workspace lifecycle evaluated", Payload: map[string]any{"schema_version": "workspace_lifecycle_audit.v1", "user_id": request.UserID, "session_id": request.SessionID, "workspace_status": workspace.Status, "lifecycle_state": workspace.LifecycleState, "age_hours": workspace.AgeHours}, StreamID: "workspace_lifecycle:" + hex.EncodeToString(sum[:])}
}

func attachmentEvent(request usecase.TaskInputPreparationRequest, fileIDs []string) *usecase.SessionEvent {
	attachments := make([]map[string]any, 0, len(request.Attachments))
	for _, attachment := range request.Attachments {
		id, name := strings.TrimSpace(attachment.FileID), strings.TrimSpace(attachment.Filename)
		if id == "" || name == "" {
			continue
		}
		mimeType := strings.TrimSpace(attachment.MimeType)
		if mimeType == "" {
			mimeType = "application/octet-stream"
		}
		size := attachment.Size
		if size < 0 {
			size = 0
		}
		attachments = append(attachments, map[string]any{"file_id": id, "filename": name, "size": size, "mime_type": mimeType})
	}
	if len(attachments) == 0 {
		return nil
	}
	return &usecase.SessionEvent{SessionID: request.SessionID, TaskID: request.TaskID, WorkflowID: request.TaskID, Type: "MESSAGE_SENT", Message: "User message sent", Payload: map[string]any{"attachments": attachments, "file_ids": fileIDs}, StreamID: "message:user:" + request.TaskID}
}

func attachmentFileIDs(attachments []usecase.FileAttachment) []string {
	ids := make([]string, 0, len(attachments))
	for _, attachment := range attachments {
		if id := strings.TrimSpace(attachment.FileID); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func stringValue(value any) string { text, _ := value.(string); return strings.TrimSpace(text) }
func stringPtr(value *string) string {
	if value == nil {
		return ""
	}
	return strings.TrimSpace(*value)
}
func int64Value(value any) int64 {
	switch value := value.(type) {
	case int64:
		return value
	case int:
		return int64(value)
	case float64:
		return int64(value)
	default:
		return 0
	}
}
