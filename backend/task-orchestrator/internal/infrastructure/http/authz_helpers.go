package httpserver

import (
	"context"
	"strings"
)

func (s *Server) authorizeTaskAccess(ctx context.Context, userID string, taskID string) bool {
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		return false
	}
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return false
	}
	sessionID, err := s.sessionDB.GetTaskSession(ctx, taskID)
	if err != nil || strings.TrimSpace(sessionID) == "" {
		return false
	}
	_, err = s.sessionDB.GetSession(ctx, sessionID, userID)
	return err == nil
}
