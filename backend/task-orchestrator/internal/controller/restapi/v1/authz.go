package v1

import (
	"context"
	"strings"

	"task-orchestrator/internal/usecase"
)

func AuthorizeTaskAccess(ctx context.Context, readModel usecase.ReadModel, userID, taskID string) bool {
	if readModel == nil || !readModel.Ready() {
		return false
	}
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return false
	}
	sessionID, err := readModel.GetTaskSession(ctx, taskID)
	if err != nil || strings.TrimSpace(sessionID) == "" {
		return false
	}
	_, err = readModel.GetSession(ctx, sessionID, userID)
	return err == nil
}
