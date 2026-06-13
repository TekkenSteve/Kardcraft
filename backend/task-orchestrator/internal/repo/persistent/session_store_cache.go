package persistent

import (
	"context"
	"strconv"
	"strings"
	"time"

	redissvc "task-orchestrator/internal/repo/redis"
)

func (s *SessionStore) invalidateSessionCache(ctx context.Context, sessionID, userID string) {
	if s == nil || s.redisSvc == nil || sessionID == "" {
		return
	}
	keys := []string{
		redissvc.SessionCachePattern(sessionID, "detail"),
		redissvc.SessionCachePattern(sessionID, "history"),
		redissvc.SessionCachePattern(sessionID, "conversation"),
		redissvc.SessionCachePattern(sessionID, "state"),
	}
	if userID != "" {
		keys = append(keys,
			redissvc.SessionCacheKey(userID, sessionID, "detail"),
			redissvc.SessionCacheKey(userID, sessionID, "history"),
			redissvc.SessionCacheKey(userID, sessionID, "conversation"),
			redissvc.SessionCacheKey(userID, sessionID, "state"),
		)
	}
	for _, pattern := range keys {
		_ = s.redisSvc.DeleteByPattern(ctx, pattern, 100)
	}
}

func (s *SessionStore) evictHotCache(ctx context.Context, sessionID, userID string) {
	if s == nil || s.redisSvc == nil || sessionID == "" {
		return
	}
	keys := []string{
		redissvc.SessionCachePattern(sessionID, "detail"),
		redissvc.SessionCachePattern(sessionID, "history"),
		redissvc.SessionCachePattern(sessionID, "conversation"),
		redissvc.SessionCachePattern(sessionID, "state"),
	}
	if userID != "" {
		keys = append(keys,
			redissvc.SessionCacheKey(userID, sessionID, "detail"),
			redissvc.SessionCacheKey(userID, sessionID, "history"),
			redissvc.SessionCacheKey(userID, sessionID, "conversation"),
			redissvc.SessionCacheKey(userID, sessionID, "state"),
		)
	}
	for _, pattern := range keys {
		_ = s.redisSvc.DeleteByPattern(ctx, pattern, 100)
	}
}

func (s *SessionStore) touchSessionActivity(ctx context.Context, sessionID, userID string) {
	if s == nil || s.redisSvc == nil || sessionID == "" || userID == "" {
		return
	}
	_ = s.redisSvc.SetString(ctx, redissvc.SessionActiveKey(userID, sessionID), strconv.FormatInt(time.Now().UTC().Unix(), 10), s.cacheTTL)
}

func (s *SessionStore) cacheGetJSON(ctx context.Context, key string, out any) bool {
	if s == nil || s.redisSvc == nil {
		return false
	}
	ok, err := s.redisSvc.GetJSON(ctx, key, out)
	if err != nil {
		return false
	}
	return ok
}

func (s *SessionStore) cacheSetJSON(ctx context.Context, key string, val any) {
	if s == nil || s.redisSvc == nil {
		return
	}
	_ = s.redisSvc.SetJSON(ctx, key, val, s.cacheTTL)
}

func nullableString(value string) any {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil
	}
	return trimmed
}
