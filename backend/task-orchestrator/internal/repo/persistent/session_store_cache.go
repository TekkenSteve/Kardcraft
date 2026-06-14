package persistent

import (
	"context"
	"strconv"
	"strings"
	"time"
)

func (s *SessionStore) invalidateSessionCache(ctx context.Context, sessionID, userID string) {
	if !s.redisEnabled() || sessionID == "" {
		return
	}
	keys := []string{
		sessionCachePattern(sessionID, "detail"),
		sessionCachePattern(sessionID, "history"),
		sessionCachePattern(sessionID, "conversation"),
		sessionCachePattern(sessionID, "state"),
	}
	if userID != "" {
		keys = append(keys,
			sessionCacheKey(userID, sessionID, "detail"),
			sessionCacheKey(userID, sessionID, "history"),
			sessionCacheKey(userID, sessionID, "conversation"),
			sessionCacheKey(userID, sessionID, "state"),
		)
	}
	for _, pattern := range keys {
		_ = s.redisDeleteByPattern(ctx, pattern, 100)
	}
}

func (s *SessionStore) evictHotCache(ctx context.Context, sessionID, userID string) {
	if !s.redisEnabled() || sessionID == "" {
		return
	}
	keys := []string{
		sessionCachePattern(sessionID, "detail"),
		sessionCachePattern(sessionID, "history"),
		sessionCachePattern(sessionID, "conversation"),
		sessionCachePattern(sessionID, "state"),
	}
	if userID != "" {
		keys = append(keys,
			sessionCacheKey(userID, sessionID, "detail"),
			sessionCacheKey(userID, sessionID, "history"),
			sessionCacheKey(userID, sessionID, "conversation"),
			sessionCacheKey(userID, sessionID, "state"),
		)
	}
	for _, pattern := range keys {
		_ = s.redisDeleteByPattern(ctx, pattern, 100)
	}
}

func (s *SessionStore) touchSessionActivity(ctx context.Context, sessionID, userID string) {
	if !s.redisEnabled() || sessionID == "" || userID == "" {
		return
	}
	_ = s.redisSetString(ctx, sessionActiveKey(userID, sessionID), strconv.FormatInt(time.Now().UTC().Unix(), 10), s.cacheTTL)
}

func (s *SessionStore) cacheGetJSON(ctx context.Context, key string, out any) bool {
	if !s.redisEnabled() {
		return false
	}
	ok, err := s.redisGetJSON(ctx, key, out)
	if err != nil {
		return false
	}
	return ok
}

func (s *SessionStore) cacheSetJSON(ctx context.Context, key string, val any) {
	if !s.redisEnabled() {
		return
	}
	_ = s.redisSetJSON(ctx, key, val, s.cacheTTL)
}

func nullableString(value string) any {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil
	}
	return trimmed
}
