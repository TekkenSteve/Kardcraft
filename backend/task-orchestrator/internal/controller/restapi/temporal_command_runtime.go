package restapi

import (
	"context"
	"fmt"
	"strings"
	"time"

	tclient "go.temporal.io/sdk/client"

	tasktemporal "task-orchestrator/internal/controller/temporal"
	"task-orchestrator/internal/usecase"
)

type temporalCommandRuntime struct {
	client    tclient.Client
	taskQueue string
}

func NewTemporalCommandRuntime(client tclient.Client, taskQueue string) usecase.CommandRuntime {
	return temporalCommandRuntime{client: client, taskQueue: taskQueue}
}

func (r temporalCommandRuntime) StartTaskWorkflow(ctx context.Context, cmd usecase.CreateTaskCommand) (string, error) {
	opts := tclient.StartWorkflowOptions{
		ID:                  cmd.TaskID,
		TaskQueue:           r.taskQueue,
		WorkflowRunTimeout:  30 * time.Minute,
		WorkflowTaskTimeout: 10 * time.Second,
	}

	taskType := strings.TrimSpace(cmd.TaskType)
	if strings.EqualFold(taskType, usecase.TaskTypeCardTemplate) {
		return r.startCardTemplateWorkflow(ctx, cmd, opts)
	}
	return "", fmt.Errorf("unsupported task_type for temporal command runtime: %s", taskType)
}

func (r temporalCommandRuntime) startCardTemplateWorkflow(ctx context.Context, cmd usecase.CreateTaskCommand, opts tclient.StartWorkflowOptions) (string, error) {
	payload := usecase.WorkflowTaskInput{
		TaskID:   cmd.TaskID,
		UserID:   cmd.UserID,
		TaskType: usecase.WorkflowTaskTypeCardTemplate,
		Input: usecase.WorkflowTaskInputPayload{
			SessionID:           cmd.Input.SessionID,
			Query:               cmd.Input.Query,
			ConversationHistory: cmd.Input.ConversationHistory,
			Context:             usecase.WorkflowTaskInputContext{TemplateID: cmd.Input.Context.TemplateID, TemplateVersion: cmd.Input.Context.TemplateVersion, TemplateProfile: cmd.Input.Context.TemplateProfile},
			FilePolicy:          cmd.Input.FilePolicy,
			ContextEnvelope:     cmd.Input.ContextEnvelope,
			FileIDs:             cmd.Input.FileIDs,
			EffectiveFileIDs:    cmd.Input.EffectiveFileIDs,
			TargetCount:         cmd.Input.TargetCount,
			DifficultyLevel:     cmd.Input.DifficultyLevel,
			TemplateID:          cmd.Input.TemplateID,
			Variables:           cmd.Input.Variables,
		},
		Config: usecase.WorkflowTaskConfig{
			ActivityTaskQueue: cmd.Config.ActivityTaskQueue,
		},
		Metadata: usecase.WorkflowTaskMetadata{
			RequestID: cmd.Metadata.RequestID,
			Source:    cmd.Metadata.Source,
			TraceID:   cmd.Metadata.TraceID,
		},
	}
	wr, err := r.client.ExecuteWorkflow(ctx, opts, usecase.TaskWorkflowName, payload)
	if err != nil {
		return "", fmt.Errorf("failed to start card template workflow: %w", err)
	}
	return wr.GetRunID(), nil
}

func (r temporalCommandRuntime) SignalWorkflow(ctx context.Context, taskID, command string, signal usecase.ControlSignal) error {
	payload := map[string]any{
		"command":    command,
		"reason":     signal.Reason,
		"request_by": signal.RequestBy,
		"timestamp":  signal.Timestamp,
	}
	return r.client.SignalWorkflow(ctx, taskID, "", tasktemporal.CommandSignalName, payload)
}

func (r temporalCommandRuntime) CancelWorkflow(ctx context.Context, taskID string) error {
	return r.client.CancelWorkflow(ctx, taskID, "")
}
