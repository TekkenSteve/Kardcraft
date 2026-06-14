package persistent

import (
	"context"
	"fmt"
	"strings"
)

func (s *SessionStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	if !s.redisEnabled() {
		return nil, fmt.Errorf("redis not configured")
	}
	out := map[string]any{}
	ok, err := s.redisGetJSON(ctx, sessionWorkspaceKey(sessionID), &out)
	if err != nil {
		return nil, err
	}
	if !ok {
		return map[string]any{
			"session_id": sessionID,
			"version":    0,
			"status":     "not_started",
			"card_count": 0,
			"cards":      []map[string]any{},
		}, nil
	}
	return out, nil
}

func (s *SessionStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	if !s.redisEnabled() {
		return fmt.Errorf("redis not configured")
	}
	if strings.TrimSpace(sessionID) == "" {
		return fmt.Errorf("session_id is required")
	}
	if workspace == nil {
		workspace = map[string]any{}
	}
	workspace["session_id"] = sessionID
	return s.redisSetJSON(ctx, sessionWorkspaceKey(sessionID), workspace, 0)
}

func (s *SessionStore) deleteWorkspace(ctx context.Context, sessionID string) {
	if !s.redisEnabled() {
		return
	}
	_ = s.redisDelete(ctx, sessionWorkspaceKey(sessionID))
}
