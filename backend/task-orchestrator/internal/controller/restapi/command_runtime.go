package restapi

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/TekkenSteve/GoAgent/agentfw/orchestration"
	tclient "go.temporal.io/sdk/client"

	"task-orchestrator/internal/controller/temporal"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
)

type commandSessionStore struct {
	store *persistent.SessionStore
}

func NewCommandSessionStore(store *persistent.SessionStore) usecase.CommandSessionStore {
	return commandSessionStore{store: store}
}

func (s commandSessionStore) UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error {
	return s.store.UpsertSession(ctx, sessionID, userID, latestQuery, latestStatus)
}

func (s commandSessionStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	return s.store.InsertTaskIfNoActive(ctx, taskID, sessionID, userID, taskType, status, query)
}

func (s commandSessionStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]usecase.SessionTask, error) {
	rows, err := s.store.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	out := make([]usecase.SessionTask, 0, len(rows))
	for _, row := range rows {
		status := ""
		if row.Status != nil {
			status = strings.TrimSpace(*row.Status)
		}
		taskType := ""
		if row.TaskType != nil {
			taskType = strings.TrimSpace(*row.TaskType)
		}
		out = append(out, usecase.SessionTask{TaskID: row.TaskID, Status: status, TaskType: taskType})
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
	if strings.EqualFold(taskType, string(temporal.TaskTypeCardTemplate)) {
		return r.startCardTemplateWorkflow(ctx, cmd, opts)
	}
	return "", fmt.Errorf("unsupported task_type for temporal command runtime: %s", taskType)
}

func (r temporalCommandRuntime) startCardTemplateWorkflow(ctx context.Context, cmd usecase.CreateTaskCommand, opts tclient.StartWorkflowOptions) (string, error) {
	payload := temporal.TaskInput{
		TaskID:   cmd.TaskID,
		UserID:   cmd.UserID,
		TaskType: temporal.TaskTypeCardTemplate,
		Input: temporal.TaskInputPayload{
			SessionID:           cmd.Input.SessionID,
			Query:               cmd.Input.Query,
			ConversationHistory: cmd.Input.ConversationHistory,
			Context:             temporal.TaskInputContext{TemplateID: cmd.Input.Context.TemplateID, TemplateVersion: cmd.Input.Context.TemplateVersion, TemplateProfile: cmd.Input.Context.TemplateProfile},
			FilePolicy:          cmd.Input.FilePolicy,
			ContextEnvelope:     cmd.Input.ContextEnvelope,
			FileIDs:             cmd.Input.FileIDs,
			EffectiveFileIDs:    cmd.Input.EffectiveFileIDs,
			TargetCount:         cmd.Input.TargetCount,
			DifficultyLevel:     cmd.Input.DifficultyLevel,
			TemplateID:          cmd.Input.TemplateID,
			Variables:           cmd.Input.Variables,
		},
		Config: temporal.TaskConfig{
			ActivityTaskQueue: cmd.Config.ActivityTaskQueue,
		},
		Metadata: temporal.TaskMetadata{
			RequestID: cmd.Metadata.RequestID,
			Source:    cmd.Metadata.Source,
			TraceID:   cmd.Metadata.TraceID,
		},
	}
	wr, err := r.client.ExecuteWorkflow(ctx, opts, temporal.TaskWorkflow, payload)
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
	return r.client.SignalWorkflow(ctx, taskID, "", orchestration.AgentCommandSignal, payload)
}

func (r temporalCommandRuntime) CancelWorkflow(ctx context.Context, taskID string) error {
	return r.client.CancelWorkflow(ctx, taskID, "")
}
