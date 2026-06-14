package command

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	goagententity "github.com/TekkenSteve/GoAgent/entity"

	"task-orchestrator/internal/usecase"
)

type UseCase struct {
	tasks    usecase.Task
	store    usecase.CommandSessionStore
	executor usecase.AgentExecutor
	runtime  usecase.CommandRuntime
	now      func() time.Time
}

func New(tasks usecase.Task, store usecase.CommandSessionStore, agentExecutor usecase.AgentExecutor, runtime usecase.CommandRuntime) *UseCase {
	return &UseCase{tasks: tasks, store: store, executor: agentExecutor, runtime: runtime, now: time.Now}
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
		activeTaskID := ""
		if listErr == nil {
			if taskID, ok := resolveActiveTaskID(tasks); ok {
				activeTaskID = taskID
			}
		}
		return nil, activeTaskID, usecase.ErrActiveTaskExists
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

	runID, err := s.startWorkflow(ctx, cmd)
	if err != nil {
		_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
		return nil, "", err
	}

	return &usecase.CreateTaskResult{
		WorkflowID: cmd.TaskID,
		RunID:      runID,
		Status:     "pending",
		SessionID:  cmd.SessionID,
	}, "", nil
}

func (s *UseCase) startWorkflow(ctx context.Context, cmd usecase.CreateTaskCommand) (string, error) {
	taskType := strings.ToLower(strings.TrimSpace(cmd.TaskType))
	if taskType == "card_template" {
		return s.runtime.StartTaskWorkflow(ctx, cmd)
	}
	if s.executor == nil {
		return "", fmt.Errorf("goagent executor is required for main task execution")
	}
	modelRef := strings.TrimSpace(cmd.Config.ModelRef)
	if modelRef == "" {
		return "", fmt.Errorf("model_ref is required for main task execution")
	}
	userMessage, err := buildAgentUserMessage(cmd)
	if err != nil {
		return "", err
	}
	status, err := s.executor.Execute(ctx, &goagententity.ExecuteRequest{
		RunID:          cmd.TaskID,
		ThreadID:       cmd.SessionID,
		AccountID:      cmd.UserID,
		ModelRef:       modelRef,
		SystemPrompt:   systemPromptFromCommand(cmd),
		UserMessage:    userMessage,
		IdempotencyKey: strings.TrimSpace(cmd.Metadata.RequestID),
		RequestedAt:    s.now().UTC(),
	})
	if err != nil {
		return "", err
	}
	return status.RunID, nil
}

func buildAgentUserMessage(cmd usecase.CreateTaskCommand) (string, error) {
	payload := map[string]any{
		"schema_version":       "kardcraft.task.input.v1",
		"task_id":              strings.TrimSpace(cmd.TaskID),
		"task_type":            strings.TrimSpace(cmd.TaskType),
		"session_id":           strings.TrimSpace(cmd.SessionID),
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
	body, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("marshal agent task input: %w", err)
	}
	return string(body), nil
}

func systemPromptFromCommand(cmd usecase.CreateTaskCommand) string {
	templateID := strings.TrimSpace(cmd.Input.Context.TemplateID)
	if templateID == "" {
		return ""
	}
	return fmt.Sprintf("Use Kardcraft template %s to help the user produce study-card content.", templateID)
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
	switch action {
	case "pause":
		if err := s.controlWorkflow(ctx, taskID, taskType, goagententity.ControlPause, signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "paused", "")
		state = "PAUSED"
	case "resume":
		if err := s.controlWorkflow(ctx, taskID, taskType, goagententity.ControlResume, signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "running", "")
		state = "RUNNING"
	case "cancel":
		if err := s.controlWorkflow(ctx, taskID, taskType, goagententity.ControlCancel, signalPayload); err != nil {
			return nil, err
		}
		if strings.EqualFold(taskType, usecase.TaskTypeCardTemplate) {
			if err := s.runtime.CancelWorkflow(ctx, taskID); err != nil {
				return nil, err
			}
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

func (s *UseCase) controlWorkflow(ctx context.Context, taskID, taskType string, op goagententity.ControlOperation, signal usecase.ControlSignal) error {
	if !strings.EqualFold(taskType, usecase.TaskTypeCardTemplate) {
		if s.executor == nil {
			return fmt.Errorf("goagent executor is required for main task control")
		}
		return s.executor.Control(ctx, taskID, op)
	}
	return s.runtime.SignalWorkflow(ctx, taskID, string(op), signal)
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
