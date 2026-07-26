package restapi

import (
	"context"
	"strings"
	"time"

	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
)

type commandSessionStore struct {
	store *persistent.SessionStore
}

func (s commandSessionStore) EnqueueConversationDispatch(ctx context.Context, item usecase.ConversationDispatch) error {
	return s.store.EnqueueConversationDispatch(ctx, item)
}

func (s commandSessionStore) ClaimConversationDispatches(ctx context.Context, limit int, staleAfter time.Duration) ([]usecase.ConversationDispatch, error) {
	return s.store.ClaimConversationDispatches(ctx, limit, staleAfter)
}

func (s commandSessionStore) MarkConversationDispatchDone(ctx context.Context, dispatchID string) error {
	return s.store.MarkConversationDispatchDone(ctx, dispatchID)
}

func (s commandSessionStore) RetryConversationDispatch(ctx context.Context, dispatchID, lastError string, nextAttempt time.Time) error {
	return s.store.RetryConversationDispatch(ctx, dispatchID, lastError, nextAttempt)
}

func (s commandSessionStore) FailConversationDispatch(ctx context.Context, dispatchID, lastError string) error {
	return s.store.FailConversationDispatch(ctx, dispatchID, lastError)
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
