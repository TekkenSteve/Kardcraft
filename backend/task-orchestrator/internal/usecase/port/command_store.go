package port

import "context"

type SessionTask struct {
	TaskID string
	Status string
}

type CommandSessionStore interface {
	UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error
	InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error)
	ListSessionTasks(ctx context.Context, sessionID, userID string) ([]SessionTask, error)
	UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
	EnsureSessionAccess(ctx context.Context, sessionID, userID string) error
}
