package persistent

import (
	"strings"
	"time"

	goagentredis "github.com/TekkenSteve/GoAgent/pkg/redis"
	"github.com/jackc/pgx/v5/pgxpool"
)

type SessionStore struct {
	pg           *pgxpool.Pool
	redis        *goagentredis.Redis
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
