package command

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"task-orchestrator/internal/usecase"
)

type UseCase struct {
	tasks        usecase.Task
	store        usecase.CommandSessionStore
	execution    usecase.TaskExecution
	conversation usecase.Conversation
	outbox       usecase.ConversationDispatchOutbox
	events       usecase.SessionEventRecorder
	now          func() time.Time
}

func New(tasks usecase.Task, store usecase.CommandSessionStore, execution usecase.TaskExecution, eventRecorders ...usecase.SessionEventRecorder) (*UseCase, error) {
	return newUseCase(tasks, store, execution, nil, eventRecorders...)
}

func NewWithConversation(tasks usecase.Task, store usecase.CommandSessionStore, execution usecase.TaskExecution, conversation usecase.Conversation, eventRecorders ...usecase.SessionEventRecorder) (*UseCase, error) {
	if conversation == nil {
		return nil, fmt.Errorf("conversation is required")
	}
	return newUseCase(tasks, store, execution, conversation, eventRecorders...)
}

func newUseCase(tasks usecase.Task, store usecase.CommandSessionStore, execution usecase.TaskExecution, conversation usecase.Conversation, eventRecorders ...usecase.SessionEventRecorder) (*UseCase, error) {
	if execution == nil {
		return nil, fmt.Errorf("task execution is required")
	}
	if len(eventRecorders) == 0 || eventRecorders[0] == nil {
		return nil, fmt.Errorf("session event recorder is required")
	}
	outbox, _ := store.(usecase.ConversationDispatchOutbox)
	return &UseCase{tasks: tasks, store: store, execution: execution, conversation: conversation, outbox: outbox, events: eventRecorders[0], now: time.Now}, nil
}

func (s *UseCase) CreateTaskInSession(ctx context.Context, cmd usecase.CreateTaskCommand) (*usecase.CreateTaskResult, string, error) {
	if err := s.store.UpsertSession(ctx, cmd.SessionID, cmd.UserID, cmd.Query, "pending"); err != nil {
		return nil, "", err
	}
	inserted, err := s.store.InsertTaskIfNoActive(ctx, cmd.TaskID, cmd.SessionID, cmd.UserID, cmd.TaskType, "pending", cmd.Query)
	if err != nil {
		return nil, "", err
	}
	if !inserted {
		tasks, listErr := s.store.ListSessionTasks(ctx, cmd.SessionID, cmd.UserID)
		if listErr != nil {
			return nil, "", listErr
		}
		if existing, ok := findSessionTask(tasks, cmd.TaskID); ok {
			return s.resumeTaskStart(ctx, cmd, existing)
		}
		if activeTaskID, ok := resolveActiveTaskID(tasks); ok {
			return nil, activeTaskID, usecase.ErrActiveTaskExists
		}
		return nil, "", fmt.Errorf("task %q was not persisted after create conflict", cmd.TaskID)
	}

	_, err = s.tasks.CreateTask(ctx, usecase.CreateTaskInput{
		TaskID:    cmd.TaskID,
		TaskType:  cmd.TaskType,
		UserID:    cmd.UserID,
		Query:     cmd.Query,
		SessionID: cmd.SessionID,
	})
	if err != nil {
		_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
		return nil, "", err
	}

	return s.startTask(ctx, cmd)
}

func (s *UseCase) resumeTaskStart(ctx context.Context, cmd usecase.CreateTaskCommand, existing usecase.SessionTask) (*usecase.CreateTaskResult, string, error) {
	switch strings.ToLower(strings.TrimSpace(existing.Status)) {
	case "queued", "running", "paused":
		runID := cmd.TaskID
		var userMessage usecase.ConversationMessage
		var cursor int64
		if s.conversation != nil {
			run, err := s.startConversationRun(ctx, cmd, nil)
			if err != nil {
				return nil, "", err
			}
			runID = run.RunID
			userMessage, cursor, err = s.conversationRunSnapshot(ctx, cmd, run.RunID)
			if err != nil {
				return nil, "", err
			}
		}
		return &usecase.CreateTaskResult{
			WorkflowID:  cmd.TaskID,
			RunID:       runID,
			ProcessID:   cmd.TaskID,
			Status:      existing.Status,
			SessionID:   cmd.SessionID,
			UserMessage: userMessage,
			Cursor:      cursor,
		}, "", nil
	default:
		return s.startTask(ctx, cmd)
	}
}

func (s *UseCase) startTask(ctx context.Context, cmd usecase.CreateTaskCommand) (*usecase.CreateTaskResult, string, error) {
	conversationRunID := cmd.TaskID
	var userMessage usecase.ConversationMessage
	var cursor int64
	if s.conversation != nil {
		run, err := s.startConversationRun(ctx, cmd, nil)
		if err != nil {
			_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
			return nil, "", err
		}
		conversationRunID = run.RunID
		userMessage, cursor, err = s.conversationRunSnapshot(ctx, cmd, run.RunID)
		if err != nil {
			return nil, "", err
		}
	}
	_, err := s.startWorkflow(ctx, cmd, conversationRunID)
	if err != nil {
		_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
		return nil, "", err
	}

	return &usecase.CreateTaskResult{
		WorkflowID:  cmd.TaskID,
		RunID:       conversationRunID,
		ProcessID:   cmd.TaskID,
		Status:      "pending",
		SessionID:   cmd.SessionID,
		UserMessage: userMessage,
		Cursor:      cursor,
	}, "", nil
}

func (s *UseCase) conversationRunSnapshot(ctx context.Context, cmd usecase.CreateTaskCommand, runID string) (usecase.ConversationMessage, int64, error) {
	snapshot, err := s.conversation.GetThreadSnapshot(ctx, usecase.ConversationThreadScope{
		ThreadID: cmd.SessionID, AccountID: cmd.UserID, ProjectID: cmd.SessionID,
	})
	if err != nil {
		return usecase.ConversationMessage{}, 0, err
	}
	for i := len(snapshot.Messages) - 1; i >= 0; i-- {
		if snapshot.Messages[i].RunID == runID && snapshot.Messages[i].Role == "user" {
			return snapshot.Messages[i], snapshot.Cursor, nil
		}
	}
	return usecase.ConversationMessage{}, snapshot.Cursor, fmt.Errorf("conversation run %q has no persisted user message", runID)
}

func findSessionTask(tasks []usecase.SessionTask, taskID string) (usecase.SessionTask, bool) {
	for i := range tasks {
		if tasks[i].TaskID == taskID {
			return tasks[i], true
		}
	}

	return usecase.SessionTask{}, false
}

func (s *UseCase) startWorkflow(ctx context.Context, cmd usecase.CreateTaskCommand, conversationRunID string) (string, error) {
	if s.execution == nil {
		return "", fmt.Errorf("task execution is required")
	}
	modelRef := strings.TrimSpace(cmd.Config.ModelRef)
	executionInput := buildTaskExecutionInput(cmd, conversationRunID)
	request := usecase.TaskExecutionRequest{
		RunID:          cmd.TaskID,
		ThreadID:       cmd.SessionID,
		AccountID:      cmd.UserID,
		ProjectID:      cmd.SessionID,
		ModelRef:       modelRef,
		SystemPrompt:   systemPromptFromCommand(cmd),
		UserMessage:    strings.TrimSpace(cmd.Input.Query),
		IdempotencyKey: strings.TrimSpace(cmd.Metadata.RequestID),
		RequestedAt:    s.now().UTC(),
		Input:          executionInput,
	}
	if s.outbox != nil {
		if err := s.enqueueConversationDispatch(ctx, conversationDispatchPayload{Start: &request}, usecase.ConversationDispatch{
			IdempotencyKey: "start:" + strings.TrimSpace(cmd.Metadata.RequestID),
			ThreadID:       cmd.SessionID, RunID: conversationRunID, ProcessID: cmd.TaskID,
			AccountID: cmd.UserID, ProjectID: cmd.SessionID, Kind: "start",
		}); err != nil {
			return "", err
		}
		_ = s.DispatchPendingConversations(ctx, 1)
		return cmd.TaskID, nil
	}
	status, err := s.execution.StartTaskExecution(ctx, request)
	if err != nil {
		return "", err
	}
	return status.RunID, nil
}

func buildTaskExecutionInput(cmd usecase.CreateTaskCommand, conversationRunID string) map[string]any {
	return map[string]any{
		"schema_version":       "kardcraft.task.input.v1",
		"task_id":              strings.TrimSpace(cmd.TaskID),
		"task_type":            strings.TrimSpace(cmd.TaskType),
		"session_id":           strings.TrimSpace(cmd.SessionID),
		"conversation_run_id":  strings.TrimSpace(conversationRunID),
		"query":                strings.TrimSpace(cmd.Input.Query),
		"conversation_history": cmd.Input.ConversationHistory,
		"context": map[string]any{
			"template_id":      strings.TrimSpace(cmd.Input.Context.TemplateID),
			"template_version": cmd.Input.Context.TemplateVersion,
			"template_profile": strings.TrimSpace(cmd.Input.Context.TemplateProfile),
		},
		"file_policy":        strings.TrimSpace(cmd.Input.FilePolicy),
		"file_ids":           cmd.Input.FileIDs,
		"effective_file_ids": cmd.Input.EffectiveFileIDs,
		"context_envelope":   cmd.Input.ContextEnvelope,
		"target_count":       cmd.Input.TargetCount,
		"difficulty_level":   strings.TrimSpace(cmd.Input.DifficultyLevel),
		"template_id":        strings.TrimSpace(cmd.Input.TemplateID),
		"variables":          cmd.Input.Variables,
	}
}

func (s *UseCase) startConversationRun(ctx context.Context, cmd usecase.CreateTaskCommand, resume *usecase.ConversationResume) (usecase.ConversationRun, error) {
	requestedAt := s.now().UTC()
	attachments := make([]usecase.ConversationAttachment, 0, len(cmd.Attachments))
	for _, attachment := range cmd.Attachments {
		attachments = append(attachments, usecase.ConversationAttachment{
			FileID: attachment.FileID, Filename: attachment.Filename,
			Size: attachment.Size, MIMEType: attachment.MimeType,
		})
	}
	return s.conversation.StartRun(ctx, usecase.ConversationStartRequest{
		ThreadID: cmd.SessionID, ProcessID: cmd.TaskID, AccountID: cmd.UserID, ProjectID: cmd.SessionID,
		UserMessage: strings.TrimSpace(cmd.Input.Query), Attachments: attachments,
		IdempotencyKey: strings.TrimSpace(cmd.Metadata.RequestID),
		RunMetadata:    map[string]any{"task_type": cmd.TaskType, "source": cmd.Metadata.Source},
		Resume:         resume, RequestedAt: requestedAt,
	})
}

func systemPromptFromCommand(cmd usecase.CreateTaskCommand) string {
	templateID := strings.TrimSpace(cmd.Input.Context.TemplateID)
	if templateID == "" {
		return ""
	}
	return fmt.Sprintf("Use Kardcraft template %s to help the user produce study-card content.", templateID)
}

func (s *UseCase) SendMessageToSession(ctx context.Context, cmd usecase.SessionMessageCommand) (*usecase.SessionMessageResult, error) {
	if s.execution == nil {
		return nil, fmt.Errorf("task execution is required for session messages")
	}
	if err := s.store.EnsureSessionAccess(ctx, cmd.SessionID, cmd.UserID); err != nil {
		return nil, err
	}
	tasks, err := s.store.ListSessionTasks(ctx, cmd.SessionID, cmd.UserID)
	if err != nil {
		return nil, err
	}
	taskID, _, ok := resolveActiveTask(tasks)
	if !ok {
		return nil, usecase.ErrNoActiveTask
	}
	sentAt := cmd.SentAt
	if sentAt.IsZero() {
		sentAt = s.now().UTC()
	}
	idempotencyKey := strings.TrimSpace(cmd.IdempotencyKey)
	if idempotencyKey == "" {
		return nil, fmt.Errorf("idempotency key is required")
	}
	conversationRunID := taskID
	var userMessage usecase.ConversationMessage
	var cursor int64
	if s.conversation != nil {
		attachments := make([]usecase.ConversationAttachment, 0, len(cmd.Attachments))
		for _, attachment := range cmd.Attachments {
			attachments = append(attachments, usecase.ConversationAttachment{
				FileID: stringMapValue(attachment, "file_id"), Filename: stringMapValue(attachment, "filename"),
				Size: int64MapValue(attachment, "size"), MIMEType: stringMapValue(attachment, "mime_type"),
			})
		}
		var resume *usecase.ConversationResume
		if strings.TrimSpace(cmd.InterruptID) != "" {
			resume = &usecase.ConversationResume{InterruptID: strings.TrimSpace(cmd.InterruptID), Response: cmd.Content}
		}
		run, err := s.conversation.StartRun(ctx, usecase.ConversationStartRequest{
			RunID: uuid.NewString(), ThreadID: cmd.SessionID, ProcessID: taskID,
			AccountID: cmd.UserID, ProjectID: cmd.SessionID, MessageID: uuid.NewString(),
			UserMessage: strings.TrimSpace(cmd.Content), Attachments: attachments,
			MessageMetadata: cmd.Metadata, Resume: resume, IdempotencyKey: idempotencyKey, RequestedAt: sentAt,
		})
		if err != nil {
			return nil, err
		}
		conversationRunID = run.RunID
		snapshot, err := s.conversation.GetThreadSnapshot(ctx, usecase.ConversationThreadScope{
			ThreadID: cmd.SessionID, AccountID: cmd.UserID, ProjectID: cmd.SessionID,
		})
		if err != nil {
			return nil, err
		}
		cursor = snapshot.Cursor
		for i := len(snapshot.Messages) - 1; i >= 0; i-- {
			if snapshot.Messages[i].RunID == run.RunID && snapshot.Messages[i].Role == "user" {
				userMessage = snapshot.Messages[i]
				break
			}
		}
	}
	payload := map[string]any{
		"schema_version":      "kardcraft.user_message.v1",
		"session_id":          strings.TrimSpace(cmd.SessionID),
		"user_id":             strings.TrimSpace(cmd.UserID),
		"active_task_id":      taskID,
		"conversation_run_id": conversationRunID,
		"interrupt_id":        strings.TrimSpace(cmd.InterruptID),
		"content":             strings.TrimSpace(cmd.Content),
		"attachments":         cmd.Attachments,
		"file_ids":            cmd.FileIDs,
		"context":             cmd.Context,
		"context_envelope":    cmd.ContextEnvelope,
		"metadata":            cmd.Metadata,
	}
	signal := usecase.TaskExecutionSignal{
		Type:           usecase.AgentSignalUserMessage,
		IdempotencyKey: idempotencyKey,
		ActorID:        strings.TrimSpace(cmd.UserID),
		Payload:        payload,
		SentAt:         sentAt,
	}
	if s.outbox != nil {
		if err := s.enqueueConversationDispatch(ctx, conversationDispatchPayload{SignalTaskID: taskID, Signal: &signal}, usecase.ConversationDispatch{
			IdempotencyKey: "resume:" + idempotencyKey,
			ThreadID:       cmd.SessionID, RunID: conversationRunID, ProcessID: taskID,
			AccountID: cmd.UserID, ProjectID: cmd.SessionID, Kind: "resume",
		}); err != nil {
			return nil, err
		}
		_ = s.DispatchPendingConversations(ctx, 1)
	} else if err := s.execution.SignalTaskExecution(ctx, taskID, signal); err != nil {
		return nil, err
	}
	streamID := sessionMessageStreamID(cmd.SessionID, taskID, idempotencyKey)
	if s.conversation == nil {
		if err := s.RecordSessionEvents(ctx, []usecase.SessionEvent{{
			SessionID: cmd.SessionID, TaskID: taskID, WorkflowID: taskID, Type: "MESSAGE_SENT", Message: "User message sent",
			Payload: map[string]any{
				"schema_version": "kardcraft.user_message.v1",
				"content":        strings.TrimSpace(cmd.Content), "attachments": cmd.Attachments, "file_ids": cmd.FileIDs,
				"context": cmd.Context, "context_envelope": cmd.ContextEnvelope, "metadata": cmd.Metadata,
			},
			StreamID: streamID, OccurredAt: sentAt,
		}}); err != nil {
			return nil, err
		}
	}
	return &usecase.SessionMessageResult{
		SessionID:      cmd.SessionID,
		ActiveTaskID:   taskID,
		RunID:          conversationRunID,
		ProcessID:      taskID,
		UserMessage:    userMessage,
		Cursor:         cursor,
		IdempotencyKey: idempotencyKey,
		StreamID:       streamID,
		SentAt:         sentAt,
	}, nil
}

func stringMapValue(record map[string]any, key string) string {
	value, _ := record[key].(string)
	return strings.TrimSpace(value)
}

func int64MapValue(record map[string]any, key string) int64 {
	switch value := record[key].(type) {
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

func (s *UseCase) RecordSessionEvents(ctx context.Context, events []usecase.SessionEvent) error {
	if s.events == nil {
		return fmt.Errorf("session event recorder is required")
	}
	for _, event := range events {
		payloadBytes, err := json.Marshal(event.Payload)
		if err != nil {
			return fmt.Errorf("encode session event %s: %w", event.Type, err)
		}
		occurredAt := event.OccurredAt
		if occurredAt.IsZero() {
			occurredAt = s.now().UTC()
		}
		if err := s.events.InsertEvent(ctx, event.SessionID, event.TaskID, event.WorkflowID, event.Type, event.Message, string(payloadBytes), event.StreamID, occurredAt); err != nil {
			return fmt.Errorf("record session event %s: %w", event.Type, err)
		}
	}
	return nil
}

func sessionMessageStreamID(sessionID, taskID, idempotencyKey string) string {
	sum := sha1.Sum([]byte(strings.Join([]string{
		"session-message", strings.TrimSpace(sessionID), strings.TrimSpace(taskID), strings.TrimSpace(idempotencyKey),
	}, "|")))
	return "message:user:" + hex.EncodeToString(sum[:])
}

func (s *UseCase) ControlSession(ctx context.Context, cmd usecase.SessionControlCommand) (*usecase.SessionControlResult, error) {
	if err := s.store.EnsureSessionAccess(ctx, cmd.SessionID, cmd.UserID); err != nil {
		return nil, err
	}
	tasks, err := s.store.ListSessionTasks(ctx, cmd.SessionID, cmd.UserID)
	if err != nil {
		return nil, err
	}
	taskID, state, ok := resolveControlTask(tasks, cmd.TaskID)
	if !ok {
		return nil, usecase.ErrNoActiveTask
	}
	taskType := resolveTaskType(tasks, taskID)
	action := strings.ToLower(strings.TrimSpace(cmd.Action))
	if err := validateTransition(action, state); err != nil {
		return nil, err
	}
	signalPayload := usecase.ControlSignal{
		Reason:    cmd.Reason,
		RequestBy: cmd.UserID,
		Timestamp: s.now().UTC(),
	}
	idempotencyKey := strings.TrimSpace(cmd.IdempotencyKey)
	if idempotencyKey == "" {
		return nil, fmt.Errorf("idempotency key is required")
	}
	switch action {
	case "pause":
		if err := s.controlWorkflow(ctx, taskID, taskType, usecase.AgentControlPause, idempotencyKey, signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "paused", "")
		state = "PAUSED"
	case "resume":
		if err := s.controlWorkflow(ctx, taskID, taskType, usecase.AgentControlResume, idempotencyKey, signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "running", "")
		state = "RUNNING"
	case "cancel":
		if err := s.controlWorkflow(ctx, taskID, taskType, usecase.AgentControlCancel, idempotencyKey, signalPayload); err != nil {
			return nil, err
		}
		state = "TERMINATING"
	default:
		return nil, fmt.Errorf("unsupported action: %s", cmd.Action)
	}

	return &usecase.SessionControlResult{
		SessionID:           cmd.SessionID,
		ActiveTaskID:        taskID,
		TaskState:           state,
		SessionControlState: controlStateFromTaskState(state),
		Accepted:            action == "cancel",
	}, nil
}

func (s *UseCase) controlWorkflow(ctx context.Context, taskID, taskType string, op usecase.AgentControlOperation, idempotencyKey string, signal usecase.ControlSignal) error {
	if s.execution == nil {
		return fmt.Errorf("task execution is required for task control")
	}
	_ = taskType
	return s.execution.ControlTaskExecution(ctx, taskID, usecase.TaskExecutionControl{
		Operation:      op,
		IdempotencyKey: idempotencyKey,
		RequestedAt:    signal.Timestamp,
		ActorID:        strings.TrimSpace(signal.RequestBy),
		Metadata: map[string]string{
			"reason": strings.TrimSpace(signal.Reason),
		},
	})
}

func validateTransition(action, state string) error {
	switch action {
	case "pause":
		if state != "RUNNING" {
			return fmt.Errorf("%w: active task is not running", usecase.ErrInvalidTransition)
		}
	case "resume":
		if state != "PAUSED" {
			return fmt.Errorf("%w: active task is not paused", usecase.ErrInvalidTransition)
		}
	case "cancel":
		if state != "RUNNING" && state != "PAUSED" {
			return fmt.Errorf("%w: active task is not cancellable", usecase.ErrInvalidTransition)
		}
	default:
		return fmt.Errorf("unsupported action: %s", action)
	}
	return nil
}

func resolveActiveTask(tasks []usecase.SessionTask) (string, string, bool) {
	if taskID, ok := resolveActiveTaskID(tasks); ok {
		for _, t := range tasks {
			if t.TaskID == taskID {
				return taskID, normalizeTaskStateForControl(t.Status), true
			}
		}
	}
	return "", "", false
}

func resolveControlTask(tasks []usecase.SessionTask, requestedTaskID string) (string, string, bool) {
	taskID := strings.TrimSpace(requestedTaskID)
	if taskID == "" {
		return resolveActiveTask(tasks)
	}
	for _, t := range tasks {
		if t.TaskID == taskID {
			return taskID, normalizeTaskStateForControl(t.Status), true
		}
	}
	return "", "", false
}

func resolveActiveTaskID(tasks []usecase.SessionTask) (string, bool) {
	for i := len(tasks) - 1; i >= 0; i-- {
		st := strings.ToLower(strings.TrimSpace(tasks[i].Status))
		if st == "pending" || st == "queued" || st == "running" || st == "paused" {
			return tasks[i].TaskID, true
		}
	}
	return "", false
}

func resolveTaskType(tasks []usecase.SessionTask, taskID string) string {
	for _, t := range tasks {
		if t.TaskID == taskID {
			return strings.TrimSpace(t.TaskType)
		}
	}
	return ""
}

func normalizeTaskStateForControl(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "pending", "queued":
		return "QUEUED"
	case "running":
		return "RUNNING"
	case "paused":
		return "PAUSED"
	case "completed":
		return "COMPLETED"
	case "failed":
		return "FAILED"
	case "cancelled", "canceled":
		return "CANCELLED"
	default:
		return "IDLE"
	}
}

func controlStateFromTaskState(state string) string {
	switch state {
	case "QUEUED", "RUNNING":
		return "ACTIVE_RUNNING"
	case "PAUSED":
		return "ACTIVE_PAUSED"
	case "TERMINATING":
		return "TERMINATING"
	default:
		return "IDLE"
	}
}
