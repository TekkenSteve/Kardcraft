package persistent

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	goagentredis "github.com/TekkenSteve/GoAgent/pkg/redis"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type SessionStoreConfig struct {
	PostgresDSN   string
	RedisAddr     string
	RedisPassword string
	RedisDB       int
	CacheTTL      time.Duration
	ActiveWindow  time.Duration
	CleanupEvery  time.Duration
	CleanupBatch  int
}

type SessionRow struct {
	SessionID        string     `json:"session_id"`
	UserID           string     `json:"user_id"`
	Title            *string    `json:"title,omitempty"`
	Pinned           bool       `json:"pinned"`
	TaskCount        int        `json:"task_count"`
	TokensUsed       int        `json:"tokens_used"`
	TotalCostUSD     float64    `json:"total_cost_usd"`
	CreatedAt        time.Time  `json:"created_at"`
	UpdatedAt        time.Time  `json:"updated_at"`
	LastActivityAt   *time.Time `json:"last_activity_at,omitempty"`
	LatestTaskQuery  *string    `json:"latest_task_query,omitempty"`
	LatestTaskStatus *string    `json:"latest_task_status,omitempty"`
}

type TaskRow struct {
	TaskID      string     `json:"task_id"`
	WorkflowID  string     `json:"workflow_id"`
	Query       *string    `json:"query,omitempty"`
	Status      *string    `json:"status,omitempty"`
	TaskType    *string    `json:"mode,omitempty"`
	Result      any        `json:"result,omitempty"`
	Error       *string    `json:"error_message,omitempty"`
	StartedAt   *time.Time `json:"started_at,omitempty"`
	CompletedAt *time.Time `json:"completed_at,omitempty"`
	DurationMS  *int64     `json:"duration_ms,omitempty"`
}

type EventRow struct {
	ID        int64     `json:"seq"`
	TaskID    *string   `json:"task_id,omitempty"`
	Workflow  *string   `json:"workflow_id,omitempty"`
	Type      string    `json:"type"`
	Message   *string   `json:"message,omitempty"`
	Payload   *string   `json:"payload,omitempty"`
	StreamID  *string   `json:"stream_id,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}

type UsageLedgerRow struct {
	IdempotencyKey    string
	SchemaVersion     string
	TaskID            string
	WorkflowID        string
	SessionID         string
	UserID            string
	Intent            string
	Provider          string
	Model             string
	PromptTokens      int
	CompletionTokens  int
	CacheReadTokens   int
	CacheWriteTokens  int
	TotalTokens       int
	InputCostUSD      float64
	OutputCostUSD     float64
	CacheCostUSD      float64
	TotalCostUSD      float64
	Estimated         bool
	Source            string
	ExternalRequestID string
	Metadata          map[string]any
	CreatedAt         time.Time
}

type ModelUsageBreakdown struct {
	Model               string  `json:"model"`
	Provider            string  `json:"provider"`
	Executions          int     `json:"executions"`
	Tokens              int     `json:"tokens"`
	CostUSD             float64 `json:"cost_usd"`
	PromptTokens        int     `json:"prompt_tokens"`
	CompletionTokens    int     `json:"completion_tokens"`
	CacheReadTokens     int     `json:"cache_read_tokens"`
	CacheWriteTokens    int     `json:"cache_write_tokens"`
	EstimatedExecutions int     `json:"estimated_executions"`
}

type TaskUsageSummary struct {
	TotalTokens      int
	PromptTokens     int
	CompletionTokens int
	CacheReadTokens  int
	CacheWriteTokens int
	TotalCostUSD     float64
	ModelBreakdown   []ModelUsageBreakdown
}

type TemplateCatalogRow struct {
	TemplateID             string         `json:"template_id"`
	Name                   string         `json:"name"`
	Description            string         `json:"description,omitempty"`
	Scope                  string         `json:"scope"`
	OwnerUserID            string         `json:"owner_user_id,omitempty"`
	Status                 string         `json:"status"`
	IsDefault              bool           `json:"is_default"`
	LatestVersion          int            `json:"latest_version"`
	VersionPublished       bool           `json:"version_published"`
	CreatedAt              time.Time      `json:"created_at"`
	UpdatedAt              time.Time      `json:"updated_at"`
	Tags                   map[string]any `json:"-"`
	Metadata               map[string]any `json:"-"`
	FrontHTML              string         `json:"-"`
	BackHTML               string         `json:"-"`
	CSS                    string         `json:"-"`
	JS                     string         `json:"-"`
	MappingSpec            map[string]any `json:"-"`
	DefaultTemplateID      string         `json:"-"`
	DefaultTemplateVersion int            `json:"-"`
}

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

func (s *SessionStore) redisEnabled() bool {
	return s != nil && s.redis != nil
}

func (s *SessionStore) redisGetString(ctx context.Context, key string) (string, error) {
	if !s.redisEnabled() {
		return "", errors.New("redis not configured")
	}
	return s.redis.Get(ctx, key)
}

func (s *SessionStore) redisSetString(ctx context.Context, key, value string, ttl time.Duration) error {
	if !s.redisEnabled() {
		return errors.New("redis not configured")
	}
	return s.redis.Set(ctx, key, value, ttl)
}

func (s *SessionStore) redisDelete(ctx context.Context, keys ...string) error {
	if !s.redisEnabled() || len(keys) == 0 {
		return nil
	}
	_, err := s.redis.Del(ctx, keys...)
	return err
}

func (s *SessionStore) redisGetJSON(ctx context.Context, key string, out any) (bool, error) {
	raw, err := s.redisGetString(ctx, key)
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return false, nil
		}
		return false, err
	}
	if strings.TrimSpace(raw) == "" {
		return false, nil
	}
	if err := json.Unmarshal([]byte(raw), out); err != nil {
		return false, err
	}
	return true, nil
}

func (s *SessionStore) redisSetJSON(ctx context.Context, key string, value any, ttl time.Duration) error {
	if !s.redisEnabled() {
		return errors.New("redis not configured")
	}
	b, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return s.redisSetString(ctx, key, string(b), ttl)
}

func (s *SessionStore) redisDeleteByPattern(ctx context.Context, pattern string, scanCount int) error {
	if !s.redisEnabled() {
		return errors.New("redis not configured")
	}
	if scanCount <= 0 {
		scanCount = 100
	}
	var cursor uint64
	for {
		keys, next, err := s.redis.GeneralClient.Scan(ctx, cursor, pattern, int64(scanCount)).Result()
		if err != nil {
			return err
		}
		if len(keys) > 0 {
			if _, err := s.redis.DelMultiple(ctx, keys); err != nil {
				return err
			}
		}
		cursor = next
		if cursor == 0 {
			return nil
		}
	}
}
