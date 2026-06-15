package persistent

import (
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type SessionStore struct {
	pg           *pgxpool.Pool
	redis        *redis.Client
	cacheTTL     time.Duration
	activeWindow time.Duration
	cleanupEvery time.Duration
	cleanupBatch int
}

func taskSessionKey(taskID string) string {
	return "task:session:" + strings.TrimSpace(taskID)
}

func sessionWorkspaceKey(sessionID string) string {
	return "pack:session:" + strings.TrimSpace(sessionID)
}

func sessionCacheKey(userID, sessionID, suffix string) string {
	return "sess:" + strings.TrimSpace(userID) + ":" + strings.TrimSpace(sessionID) + ":" + strings.TrimSpace(suffix)
}

func sessionCachePattern(sessionID, suffix string) string {
	return "sess:*:" + strings.TrimSpace(sessionID) + ":" + strings.TrimSpace(suffix)
}

func sessionActiveKey(userID, sessionID string) string {
	return sessionCacheKey(userID, sessionID, "active")
}
