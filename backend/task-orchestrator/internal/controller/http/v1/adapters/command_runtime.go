package adapters

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/TekkenSteve/GoAgent/agentfw/orchestration"
	"github.com/TekkenSteve/GoAgent/entity"
	tclient "go.temporal.io/sdk/client"

	"task-orchestrator/internal/repo/persistence"
	"task-orchestrator/internal/runtime/temporal/workflows"
	"task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

type commandSessionStore struct {
	store *persistence.SessionStore
}

func NewCommandSessionStore(store *persistence.SessionStore) port.CommandSessionStore {
	return commandSessionStore{store: store}
}

func (s commandSessionStore) UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error {
	return s.store.UpsertSession(ctx, sessionID, userID, latestQuery, latestStatus)
}

func (s commandSessionStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	return s.store.InsertTaskIfNoActive(ctx, taskID, sessionID, userID, taskType, status, query)
}

func (s commandSessionStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]port.SessionTask, error) {
	rows, err := s.store.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	out := make([]port.SessionTask, 0, len(rows))
	for _, row := range rows {
		status := ""
		if row.Status != nil {
			status = strings.TrimSpace(*row.Status)
		}
		out = append(out, port.SessionTask{TaskID: row.TaskID, Status: status})
	}
	return out, nil
}

func (s commandSessionStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return s.store.UpdateTaskStatus(ctx, taskID, status, errMsg)
}

func (s commandSessionStore) EnsureSessionAccess(ctx context.Context, sessionID, userID string) error {
	_, err := s.store.GetSession(ctx, sessionID, userID)
	return err
}

type temporalCommandRuntime struct {
	client    tclient.Client
	taskQueue string
}

func NewTemporalCommandRuntime(client tclient.Client, taskQueue string) port.CommandRuntime {
	return temporalCommandRuntime{client: client, taskQueue: taskQueue}
}

func (r temporalCommandRuntime) StartTaskWorkflow(ctx context.Context, cmd dto.CreateTaskCommand) (string, error) {
	opts := tclient.StartWorkflowOptions{
		ID:                  cmd.TaskID,
		TaskQueue:           r.taskQueue,
		WorkflowRunTimeout:  30 * time.Minute,
		WorkflowTaskTimeout: 10 * time.Second,
	}

	taskType := strings.TrimSpace(cmd.TaskType)
	if strings.EqualFold(taskType, string(workflows.TaskTypeCardTemplate)) {
		return r.startCardTemplateWorkflow(ctx, cmd, opts)
	}
	return r.startOrchestrationWorkflow(ctx, cmd, opts)
}

func (r temporalCommandRuntime) startCardTemplateWorkflow(ctx context.Context, cmd dto.CreateTaskCommand, opts tclient.StartWorkflowOptions) (string, error) {
	payload := workflows.TaskInput{
		TaskID:   cmd.TaskID,
		UserID:   cmd.UserID,
		TaskType: workflows.TaskTypeCardTemplate,
		Input: workflows.TaskInputPayload{
			SessionID:           cmd.Input.SessionID,
			Query:               cmd.Input.Query,
			ConversationHistory: cmd.Input.ConversationHistory,
			Context:             workflows.TaskInputContext{TemplateID: cmd.Input.Context.TemplateID, TemplateVersion: cmd.Input.Context.TemplateVersion, TemplateProfile: cmd.Input.Context.TemplateProfile},
			FilePolicy:          cmd.Input.FilePolicy,
			ContextEnvelope:     cmd.Input.ContextEnvelope,
			FileIDs:             cmd.Input.FileIDs,
			EffectiveFileIDs:    cmd.Input.EffectiveFileIDs,
			TargetCount:         cmd.Input.TargetCount,
			DifficultyLevel:     cmd.Input.DifficultyLevel,
			TemplateID:          cmd.Input.TemplateID,
			Variables:           cmd.Input.Variables,
		},
		Config: workflows.TaskConfig{
			ActivityTaskQueue: cmd.Config.ActivityTaskQueue,
		},
		Metadata: workflows.TaskMetadata{
			RequestID: cmd.Metadata.RequestID,
			Source:    cmd.Metadata.Source,
			TraceID:   cmd.Metadata.TraceID,
		},
	}
	wr, err := r.client.ExecuteWorkflow(ctx, opts, workflows.TaskWorkflow, payload)
	if err != nil {
		return "", fmt.Errorf("failed to start card template workflow: %w", err)
	}
	return wr.GetRunID(), nil
}

func (r temporalCommandRuntime) startOrchestrationWorkflow(ctx context.Context, cmd dto.CreateTaskCommand, opts tclient.StartWorkflowOptions) (string, error) {
	input := &entity.OrchestrationInput{
		RunID:   cmd.TaskID,
		Message: cmd.Input.Query,
		Steps: []entity.Step{{
			ID:     "main",
			Type:   entity.StepAgent,
			Name:   "main",
			Input:  map[string]any{"message": cmd.Input.Query},
			Status: entity.StepPending,
		}},
	}
	wr, err := r.client.ExecuteWorkflow(ctx, opts, orchestration.OrchestrationWorkflowName, input)
	if err != nil {
		return "", fmt.Errorf("failed to start orchestration workflow: %w", err)
	}
	return wr.GetRunID(), nil
}

func (r temporalCommandRuntime) SignalWorkflow(ctx context.Context, taskID, command string, signal dto.ControlSignal) error {
	payload := map[string]any{
		"command":    command,
		"reason":     signal.Reason,
		"request_by": signal.RequestBy,
		"timestamp":  signal.Timestamp,
	}
	return r.client.SignalWorkflow(ctx, taskID, "", orchestration.AgentCommandSignal, payload)
}

func (r temporalCommandRuntime) CancelWorkflow(ctx context.Context, taskID string) error {
	return r.client.CancelWorkflow(ctx, taskID, "")
}
