package port

import (
	"context"

	"github.com/TekkenSteve/GoAgent/entity"
)

type SessionTask struct {
	TaskID   string
	Status   string
	TaskType string
}

type CommandSessionStore interface {
	UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error
	InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error)
	ListSessionTasks(ctx context.Context, sessionID, userID string) ([]SessionTask, error)
	UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
	EnsureSessionAccess(ctx context.Context, sessionID, userID string) error
}

type AgentExecutor interface {
	Execute(ctx context.Context, req *entity.ExecuteRequest) (entity.RunStatus, error)
	Control(ctx context.Context, runID string, op entity.ControlOperation) error
}
