package persistence

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	redissvc "task-orchestrator/internal/repo/redis"
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
	redis        *redis.Client
	redisSvc     *redissvc.Service
	cacheTTL     time.Duration
	activeWindow time.Duration
	cleanupEvery time.Duration
	cleanupBatch int
}

func NewSessionStore(ctx context.Context, cfg SessionStoreConfig) *SessionStore {
	if cfg.CacheTTL <= 0 {
		cfg.CacheTTL = 30 * time.Minute
	}
	if cfg.ActiveWindow <= 0 {
		cfg.ActiveWindow = 30 * time.Minute
	}
	if cfg.CleanupEvery <= 0 {
		cfg.CleanupEvery = 5 * time.Minute
	}
	if cfg.CleanupBatch <= 0 {
		cfg.CleanupBatch = 200
	}
	s := &SessionStore{
		cacheTTL:     cfg.CacheTTL,
		activeWindow: cfg.ActiveWindow,
		cleanupEvery: cfg.CleanupEvery,
		cleanupBatch: cfg.CleanupBatch,
	}
	if cfg.PostgresDSN != "" {
		pg, err := pgxpool.New(ctx, cfg.PostgresDSN)
		if err != nil {
			log.Printf("session store postgres init failed: %v", err)
		} else {
			if err := pg.Ping(ctx); err != nil {
				log.Printf("session store postgres ping failed: %v", err)
			} else {
				s.pg = pg
				if err := s.validateRequiredSchema(ctx); err != nil {
					log.Printf("session store schema validation failed: %v", err)
					pg.Close()
					s.pg = nil
				}
			}
		}
	}
	if cfg.RedisAddr != "" {
		rdb := redis.NewClient(&redis.Options{
			Addr:     cfg.RedisAddr,
			Password: cfg.RedisPassword,
			DB:       cfg.RedisDB,
		})
		if err := rdb.Ping(ctx).Err(); err != nil {
			log.Printf("session store redis ping failed: %v", err)
		} else {
			s.redis = rdb
			s.redisSvc = redissvc.NewService(rdb)
		}
	}
	return s
}

func SessionStoreConfigFromEnv() SessionStoreConfig {
	pgHost := strings.TrimSpace(os.Getenv("POSTGRES_HOST"))
	pgPort := strings.TrimSpace(os.Getenv("POSTGRES_PORT"))
	pgDB := strings.TrimSpace(os.Getenv("POSTGRES_DB"))
	pgUser := strings.TrimSpace(os.Getenv("POSTGRES_USER"))
	pgPassword := strings.TrimSpace(os.Getenv("POSTGRES_PASSWORD"))
	pgSSL := strings.TrimSpace(os.Getenv("POSTGRES_SSLMODE"))
	if pgPort == "" {
		pgPort = "5432"
	}
	if pgSSL == "" {
		pgSSL = "disable"
	}
	dsn := ""
	if pgHost != "" && pgDB != "" && pgUser != "" {
		dsn = fmt.Sprintf(
			"postgres://%s:%s@%s:%s/%s?sslmode=%s",
			pgUser,
			pgPassword,
			pgHost,
			pgPort,
			pgDB,
			pgSSL,
		)
	}

	redisHost := strings.TrimSpace(os.Getenv("REDIS_HOST"))
	redisPort := strings.TrimSpace(os.Getenv("REDIS_PORT"))
	redisPassword := strings.TrimSpace(os.Getenv("REDIS_PASSWORD"))
	if redisHost == "" {
		redisHost = "redis"
	}
	if redisPort == "" {
		redisPort = "6379"
	}
	redisDB := 0
	if raw := strings.TrimSpace(os.Getenv("REDIS_DB")); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil {
			redisDB = n
		}
	}
	activeWindow := 30 * time.Minute
	if raw := strings.TrimSpace(os.Getenv("SESSION_ACTIVE_WINDOW_SECONDS")); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			activeWindow = time.Duration(n) * time.Second
		}
	}
	cleanupEvery := 5 * time.Minute
	if raw := strings.TrimSpace(os.Getenv("SESSION_COOLDOWN_INTERVAL_SECONDS")); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			cleanupEvery = time.Duration(n) * time.Second
		}
	}
	cleanupBatch := 200
	if raw := strings.TrimSpace(os.Getenv("SESSION_COOLDOWN_BATCH")); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			cleanupBatch = n
		}
	}
	return SessionStoreConfig{
		PostgresDSN:   dsn,
		RedisAddr:     redisHost + ":" + redisPort,
		RedisPassword: redisPassword,
		RedisDB:       redisDB,
		CacheTTL:      30 * time.Minute,
		ActiveWindow:  activeWindow,
		CleanupEvery:  cleanupEvery,
		CleanupBatch:  cleanupBatch,
	}
}

func (s *SessionStore) validateRequiredSchema(ctx context.Context) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	var migrationTable string
	if err := s.pg.QueryRow(ctx, `SELECT COALESCE(to_regclass('public.kc_schema_migrations')::text, '')`).Scan(&migrationTable); err != nil {
		return fmt.Errorf("schema migration registry check failed: %w", err)
	}
	if migrationTable == "" {
		return fmt.Errorf("required table missing: kc_schema_migrations (run centralized DB migrations first)")
	}

	requiredVersion := strings.TrimSpace(os.Getenv("KC_REQUIRED_SCHEMA_VERSION"))
	if requiredVersion == "" {
		requiredVersion = "0001_initial_schema.sql"
	}
	var applied int
	if err := s.pg.QueryRow(ctx, `SELECT COUNT(*) FROM kc_schema_migrations WHERE version = $1`, requiredVersion).Scan(&applied); err != nil {
		return fmt.Errorf("schema version check failed for %s: %w", requiredVersion, err)
	}
	if applied == 0 {
		return fmt.Errorf("required schema version not applied: %s (run centralized DB migrations first)", requiredVersion)
	}
	return nil
}

func (s *SessionStore) Ready() bool {
	return s != nil && s.pg != nil && s.redis != nil
}

func (s *SessionStore) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]TemplateCatalogRow, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	var total int
	if err := s.pg.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM kc_card_templates
		WHERE status = 'active'
		  AND (scope = 'system' OR owner_user_id = $1)
	`, userID).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
		SELECT
			t.template_id,
			t.name,
			COALESCE(t.description, ''),
			t.scope,
			COALESCE(t.owner_user_id, ''),
			t.status,
			t.is_default,
			t.latest_version,
			COALESCE(v.is_published, true) AS version_published,
			t.created_at,
			t.updated_at
		FROM kc_card_templates t
		LEFT JOIN kc_card_template_versions v
		  ON v.template_id = t.template_id AND v.version = t.latest_version
		WHERE t.status = 'active'
		  AND (t.scope = 'system' OR t.owner_user_id = $1)
		ORDER BY t.updated_at DESC, t.template_id ASC
		LIMIT $2 OFFSET $3
	`, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	out := make([]TemplateCatalogRow, 0, limit)
	for rows.Next() {
		var item TemplateCatalogRow
		if err := rows.Scan(
			&item.TemplateID,
			&item.Name,
			&item.Description,
			&item.Scope,
			&item.OwnerUserID,
			&item.Status,
			&item.IsDefault,
			&item.LatestVersion,
			&item.VersionPublished,
			&item.CreatedAt,
			&item.UpdatedAt,
		); err != nil {
			return nil, 0, err
		}
		out = append(out, item)
	}
	return out, total, rows.Err()
}

func (s *SessionStore) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*TemplateCatalogRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	var item TemplateCatalogRow
	var mappingRaw string
	err := s.pg.QueryRow(ctx, `
		SELECT
			t.template_id,
			t.name,
			COALESCE(t.description, ''),
			t.scope,
			COALESCE(t.owner_user_id, ''),
			t.status,
			t.is_default,
			t.latest_version,
			COALESCE(v.is_published, true) AS version_published,
			t.created_at,
			t.updated_at,
			COALESCE(v.front_html, ''),
			COALESCE(v.back_html, ''),
			COALESCE(v.css, ''),
			COALESCE(v.js, ''),
			COALESCE(v.mapping_spec::text, '{}')
		FROM kc_card_templates t
		LEFT JOIN kc_card_template_versions v
		  ON v.template_id = t.template_id AND v.version = t.latest_version
		WHERE t.template_id = $1
		  AND t.status = 'active'
		  AND (t.scope = 'system' OR t.owner_user_id = $2)
		LIMIT 1
	`, templateID, userID).Scan(
		&item.TemplateID,
		&item.Name,
		&item.Description,
		&item.Scope,
		&item.OwnerUserID,
		&item.Status,
		&item.IsDefault,
		&item.LatestVersion,
		&item.VersionPublished,
		&item.CreatedAt,
		&item.UpdatedAt,
		&item.FrontHTML,
		&item.BackHTML,
		&item.CSS,
		&item.JS,
		&mappingRaw,
	)
	if err != nil {
		return nil, err
	}
	item.MappingSpec = make(map[string]any)
	_ = json.Unmarshal([]byte(mappingRaw), &item.MappingSpec)
	return &item, nil
}

func (s *SessionStore) GetUserTemplatePreference(ctx context.Context, userID string) (*TemplateCatalogRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	item := &TemplateCatalogRow{}
	err := s.pg.QueryRow(ctx, `
		SELECT default_template_id, COALESCE(default_template_version, 1)
		FROM kc_user_template_preferences
		WHERE user_id = $1
	`, userID).Scan(&item.DefaultTemplateID, &item.DefaultTemplateVersion)
	if err != nil {
		return nil, err
	}
	return item, nil
}

func (s *SessionStore) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	if version <= 0 {
		version = 1
	}
	_, err := s.pg.Exec(ctx, `
		INSERT INTO kc_user_template_preferences (user_id, default_template_id, default_template_version, updated_at)
		VALUES ($1, $2, $3, NOW())
		ON CONFLICT (user_id) DO UPDATE
		SET default_template_id = EXCLUDED.default_template_id,
		    default_template_version = EXCLUDED.default_template_version,
		    updated_at = NOW()
	`, userID, templateID, version)
	return err
}

func (s *SessionStore) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	if s == nil || s.pg == nil || sessionID == "" || userID == "" {
		return nil
	}
	_, err := s.pg.Exec(ctx, `
        UPDATE kc_sessions
        SET last_activity_at = NOW(), updated_at = NOW()
        WHERE session_id = $1 AND user_id = $2
    `, sessionID, userID)
	if err != nil {
		return err
	}
	s.touchSessionActivity(ctx, sessionID, userID)
	return nil
}

func (s *SessionStore) Close() {
	if s == nil {
		return
	}
	if s.pg != nil {
		s.pg.Close()
	}
	if s.redis != nil {
		_ = s.redis.Close()
	}
}

func (s *SessionStore) StartLifecycle(ctx context.Context) {
	if s == nil || s.pg == nil || s.redis == nil {
		return
	}
	ticker := time.NewTicker(s.cleanupEvery)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := s.CoolInactiveSessions(ctx); err != nil {
					log.Printf("session store cooldown failed: %v", err)
				}
			}
		}
	}()
}

func (s *SessionStore) CoolInactiveSessions(ctx context.Context) error {
	if s == nil || s.pg == nil || s.redis == nil {
		return nil
	}
	cutoff := time.Now().UTC().Add(-s.activeWindow)
	rows, err := s.pg.Query(ctx, `
        SELECT session_id, user_id
        FROM kc_sessions
        WHERE COALESCE(last_activity_at, updated_at, created_at) < $1
        ORDER BY COALESCE(last_activity_at, updated_at, created_at) ASC
        LIMIT $2
    `, cutoff, s.cleanupBatch)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var sessionID, userID string
		if err := rows.Scan(&sessionID, &userID); err != nil {
			return err
		}
		s.evictHotCache(ctx, sessionID, userID)
	}
	return rows.Err()
}

func (s *SessionStore) UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `
        INSERT INTO kc_sessions
            (session_id, user_id, title, task_count, tokens_used, created_at, updated_at, last_activity_at, latest_task_query, latest_task_status)
        VALUES
            ($1, $2, NULL, 1, 0, NOW(), NOW(), NOW(), $3, $4)
        ON CONFLICT (session_id) DO UPDATE
            SET updated_at = NOW(),
                last_activity_at = NOW(),
                latest_task_query = EXCLUDED.latest_task_query,
                latest_task_status = EXCLUDED.latest_task_status,
                user_id = EXCLUDED.user_id,
                task_count = COALESCE(kc_sessions.task_count, 0) + 1
    `, sessionID, userID, latestQuery, latestStatus)
	if err == nil {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) UpsertTask(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `
        INSERT INTO kc_tasks
            (task_id, session_id, user_id, task_type, status, query, created_at, updated_at)
        VALUES
            ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        ON CONFLICT (task_id) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = NOW(),
                query = EXCLUDED.query
	`, taskID, sessionID, userID, taskType, status, query)
	if err == nil {
		if s.redisSvc != nil {
			_ = s.redisSvc.SetString(ctx, redissvc.TaskSessionKey(taskID), sessionID, 24*time.Hour)
		}
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	if s == nil || s.pg == nil {
		return false, fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `
        INSERT INTO kc_tasks
            (task_id, session_id, user_id, task_type, status, query, created_at, updated_at)
        SELECT
            $1::text, $2::text, $3::text, $4::text, $5::text, $6::text, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1
            FROM kc_tasks
            WHERE session_id::text = $2::text
              AND user_id::text = $3::text
              AND LOWER(COALESCE(status::text, '')) IN ('pending', 'queued', 'running', 'paused')
        )
        ON CONFLICT (task_id) DO NOTHING
    `, taskID, sessionID, userID, taskType, status, query)
	if err != nil {
		return false, err
	}
	inserted := cmd.RowsAffected() > 0
	if inserted {
		if s.redisSvc != nil {
			_ = s.redisSvc.SetString(ctx, redissvc.TaskSessionKey(taskID), sessionID, 24*time.Hour)
		}
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return inserted, nil
}

func (s *SessionStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	sessionID, _ := s.GetTaskSession(ctx, taskID)
	userID := ""
	if sessionID != "" {
		_ = s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&userID)
	}
	if strings.TrimSpace(errMsg) == "" {
		_, err := s.pg.Exec(ctx, `
            UPDATE kc_tasks
            SET status = $2, updated_at = NOW()
            WHERE task_id = $1
        `, taskID, status)
		if err == nil && sessionID != "" {
			s.invalidateSessionCache(ctx, sessionID, userID)
			s.touchSessionActivity(ctx, sessionID, userID)
		}
		return err
	}
	_, err := s.pg.Exec(ctx, `
        UPDATE kc_tasks
        SET status = $2, error_message = $3, updated_at = NOW()
        WHERE task_id = $1
    `, taskID, status, errMsg)
	if err == nil && sessionID != "" {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) UpdateTaskFinalState(
	ctx context.Context,
	taskID string,
	status string,
	result any,
	errMsg string,
	completedAt time.Time,
) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	status = strings.TrimSpace(status)
	if status == "" {
		return fmt.Errorf("status is required")
	}
	if completedAt.IsZero() {
		completedAt = time.Now().UTC()
	} else {
		completedAt = completedAt.UTC()
	}

	sessionID, _ := s.GetTaskSession(ctx, taskID)
	userID := ""
	if sessionID != "" {
		_ = s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&userID)
	}

	var resultJSON any
	if result != nil {
		raw, err := json.Marshal(result)
		if err != nil {
			return fmt.Errorf("marshal task result: %w", err)
		}
		resultJSON = raw
	}

	tx, err := s.pg.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `
        UPDATE kc_tasks
        SET status = $2,
            result = COALESCE($3::jsonb, result),
            error_message = NULLIF($4, ''),
            completed_at = $5,
            updated_at = NOW()
        WHERE task_id = $1
    `, taskID, status, resultJSON, strings.TrimSpace(errMsg), completedAt); err != nil {
		return err
	}

	if sessionID != "" {
		if _, err := tx.Exec(ctx, `
	            UPDATE kc_sessions
	            SET latest_task_status = $2,
	                updated_at = $3,
	                last_activity_at = $3
	            WHERE session_id = $1
	        `, sessionID, status, completedAt); err != nil {
			return err
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return err
	}

	if sessionID != "" {
		eventType := "WORKFLOW_COMPLETED"
		message := "Workflow completed"
		switch status {
		case "failed":
			eventType = "WORKFLOW_FAILED"
			if strings.TrimSpace(errMsg) != "" {
				message = strings.TrimSpace(errMsg)
			} else {
				message = "Workflow failed"
			}
		case "cancelled", "canceled":
			eventType = "WORKFLOW_CANCELLED"
			message = "Workflow cancelled"
		}
		streamID := fmt.Sprintf("terminal:%s:%s", taskID, status)
		_ = s.InsertEvent(ctx, sessionID, taskID, taskID, eventType, message, "", streamID, completedAt)
	}

	if sessionID != "" {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return nil
}

func (s *SessionStore) InsertLLMUsage(ctx context.Context, row UsageLedgerRow) (bool, error) {
	if s == nil || s.pg == nil {
		return false, fmt.Errorf("postgres not configured")
	}
	row.IdempotencyKey = strings.TrimSpace(row.IdempotencyKey)
	if row.IdempotencyKey == "" {
		return false, fmt.Errorf("idempotency_key is required")
	}
	row.TaskID = strings.TrimSpace(row.TaskID)
	if row.TaskID == "" {
		return false, fmt.Errorf("task_id is required")
	}
	row.Provider = strings.TrimSpace(row.Provider)
	if row.Provider == "" {
		return false, fmt.Errorf("provider is required")
	}
	row.Model = strings.TrimSpace(row.Model)
	if row.Model == "" {
		return false, fmt.Errorf("model is required")
	}
	if strings.TrimSpace(row.SchemaVersion) == "" {
		row.SchemaVersion = "1"
	}
	if row.TotalTokens <= 0 {
		row.TotalTokens = row.PromptTokens + row.CompletionTokens
	}
	if row.TotalTokens < 0 {
		row.TotalTokens = 0
	}
	if row.PromptTokens < 0 {
		row.PromptTokens = 0
	}
	if row.CompletionTokens < 0 {
		row.CompletionTokens = 0
	}
	if row.CacheReadTokens < 0 {
		row.CacheReadTokens = 0
	}
	if row.CacheWriteTokens < 0 {
		row.CacheWriteTokens = 0
	}
	if row.InputCostUSD < 0 {
		row.InputCostUSD = 0
	}
	if row.OutputCostUSD < 0 {
		row.OutputCostUSD = 0
	}
	if row.CacheCostUSD < 0 {
		row.CacheCostUSD = 0
	}
	if row.TotalCostUSD < 0 {
		row.TotalCostUSD = 0
	}
	if strings.TrimSpace(row.Source) == "" {
		if row.Estimated {
			row.Source = "estimated"
		} else {
			row.Source = "exact"
		}
	}
	if row.CreatedAt.IsZero() {
		row.CreatedAt = time.Now().UTC()
	} else {
		row.CreatedAt = row.CreatedAt.UTC()
	}

	if strings.TrimSpace(row.SessionID) == "" {
		sessionID, err := s.GetTaskSession(ctx, row.TaskID)
		if err != nil {
			return false, fmt.Errorf("resolve session_id by task_id: %w", err)
		}
		row.SessionID = strings.TrimSpace(sessionID)
	}
	if row.SessionID == "" {
		return false, fmt.Errorf("session_id is required")
	}
	if strings.TrimSpace(row.UserID) == "" {
		if err := s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, row.TaskID).Scan(&row.UserID); err != nil {
			return false, fmt.Errorf("resolve user_id by task_id: %w", err)
		}
		row.UserID = strings.TrimSpace(row.UserID)
	}
	if row.UserID == "" {
		return false, fmt.Errorf("user_id is required")
	}

	var metadataJSON any
	if row.Metadata != nil {
		raw, err := json.Marshal(row.Metadata)
		if err != nil {
			return false, fmt.Errorf("marshal llm usage metadata: %w", err)
		}
		metadataJSON = raw
	}

	tag, err := s.pg.Exec(ctx, `
		INSERT INTO kc_llm_usage_ledger (
			idempotency_key,
			schema_version,
			task_id,
			workflow_id,
			session_id,
			user_id,
			intent,
			provider,
			model,
			prompt_tokens,
			completion_tokens,
			cache_read_tokens,
			cache_write_tokens,
			total_tokens,
			input_cost_usd,
			output_cost_usd,
			cache_cost_usd,
			total_cost_usd,
			estimated,
			source,
			external_request_id,
			metadata,
			created_at
		)
		VALUES (
			$1, $2, $3, NULLIF($4, ''), $5, $6, NULLIF($7, ''), $8, $9, $10, $11, $12, $13, $14,
			$15, $16, $17, $18, $19, $20, NULLIF($21, ''), COALESCE($22::jsonb, '{}'::jsonb), $23
		)
		ON CONFLICT (idempotency_key) DO NOTHING
	`,
		row.IdempotencyKey,
		row.SchemaVersion,
		row.TaskID,
		row.WorkflowID,
		row.SessionID,
		row.UserID,
		row.Intent,
		row.Provider,
		row.Model,
		row.PromptTokens,
		row.CompletionTokens,
		row.CacheReadTokens,
		row.CacheWriteTokens,
		row.TotalTokens,
		row.InputCostUSD,
		row.OutputCostUSD,
		row.CacheCostUSD,
		row.TotalCostUSD,
		row.Estimated,
		row.Source,
		row.ExternalRequestID,
		metadataJSON,
		row.CreatedAt,
	)
	if err != nil {
		return false, err
	}
	inserted := tag.RowsAffected() > 0
	if inserted {
		s.invalidateSessionCache(ctx, row.SessionID, row.UserID)
		s.touchSessionActivity(ctx, row.SessionID, row.UserID)
	}
	return inserted, nil
}

func (s *SessionStore) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]TaskUsageSummary, error) {
	return s.getTaskUsageSummaryMap(ctx, `
		SELECT
			task_id,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(total_tokens), 0) AS total_tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
		FROM kc_llm_usage_ledger
		WHERE session_id = $1 AND user_id = $2
		GROUP BY task_id
	`, sessionID, userID)
}

func (s *SessionStore) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]TaskUsageSummary, error) {
	if len(taskIDs) == 0 {
		return map[string]TaskUsageSummary{}, nil
	}
	filtered := make([]string, 0, len(taskIDs))
	for _, id := range taskIDs {
		if strings.TrimSpace(id) != "" {
			filtered = append(filtered, strings.TrimSpace(id))
		}
	}
	if len(filtered) == 0 {
		return map[string]TaskUsageSummary{}, nil
	}
	return s.getTaskUsageSummaryMap(ctx, `
		SELECT
			task_id,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(total_tokens), 0) AS total_tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
		FROM kc_llm_usage_ledger
		WHERE user_id = $1 AND task_id = ANY($2)
		GROUP BY task_id
	`, userID, filtered)
}

func (s *SessionStore) getTaskUsageSummaryMap(ctx context.Context, summaryQuery string, args ...any) (map[string]TaskUsageSummary, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, summaryQuery, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	summary := make(map[string]TaskUsageSummary)
	for rows.Next() {
		var taskID string
		var item TaskUsageSummary
		if err := rows.Scan(
			&taskID,
			&item.PromptTokens,
			&item.CompletionTokens,
			&item.CacheReadTokens,
			&item.CacheWriteTokens,
			&item.TotalTokens,
			&item.TotalCostUSD,
		); err != nil {
			return nil, err
		}
		summary[taskID] = item
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	breakdownRows, err := s.pg.Query(ctx, `
		SELECT
			task_id,
			model,
			provider,
			COUNT(*) AS executions,
			COALESCE(SUM(total_tokens), 0) AS tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS cost_usd,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(CASE WHEN estimated THEN 1 ELSE 0 END), 0) AS estimated_executions
		FROM kc_llm_usage_ledger
		WHERE task_id = ANY($1)
		GROUP BY task_id, model, provider
		ORDER BY task_id ASC, cost_usd DESC, model ASC
	`, mapsKeys(summary))
	if err != nil {
		return nil, err
	}
	defer breakdownRows.Close()
	for breakdownRows.Next() {
		var taskID string
		entry := ModelUsageBreakdown{}
		if err := breakdownRows.Scan(
			&taskID,
			&entry.Model,
			&entry.Provider,
			&entry.Executions,
			&entry.Tokens,
			&entry.CostUSD,
			&entry.PromptTokens,
			&entry.CompletionTokens,
			&entry.CacheReadTokens,
			&entry.CacheWriteTokens,
			&entry.EstimatedExecutions,
		); err != nil {
			return nil, err
		}
		item := summary[taskID]
		item.ModelBreakdown = append(item.ModelBreakdown, entry)
		summary[taskID] = item
	}
	if err := breakdownRows.Err(); err != nil {
		return nil, err
	}
	return summary, nil
}

func mapsKeys(m map[string]TaskUsageSummary) []string {
	out := make([]string, 0, len(m))
	for key := range m {
		out = append(out, key)
	}
	return out
}

func (s *SessionStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	if s == nil {
		return "", fmt.Errorf("session store not initialized")
	}
	if s.redisSvc != nil {
		if sid, err := s.redisSvc.GetString(ctx, redissvc.TaskSessionKey(taskID)); err == nil && sid != "" {
			return sid, nil
		}
	}
	if s.pg == nil {
		return "", fmt.Errorf("postgres not configured")
	}
	var sessionID string
	err := s.pg.QueryRow(ctx, `SELECT session_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&sessionID)
	if err == nil && s.redisSvc != nil && sessionID != "" {
		_ = s.redisSvc.SetString(ctx, redissvc.TaskSessionKey(taskID), sessionID, 24*time.Hour)
	}
	return sessionID, err
}

func (s *SessionStore) GetSession(ctx context.Context, sessionID, userID string) (*SessionRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	cacheKey := redissvc.SessionCacheKey(userID, sessionID, "detail")
	var cached SessionRow
	if s.cacheGetJSON(ctx, cacheKey, &cached) {
		s.touchSessionActivity(ctx, sessionID, userID)
		return &cached, nil
	}

	row := &SessionRow{}
	err := s.pg.QueryRow(ctx, `
        SELECT session_id, user_id, title, pinned, task_count, tokens_used, created_at, updated_at, last_activity_at, latest_task_query, latest_task_status
        FROM kc_sessions
        WHERE session_id = $1 AND user_id = $2
    `, sessionID, userID).Scan(
		&row.SessionID,
		&row.UserID,
		&row.Title,
		&row.Pinned,
		&row.TaskCount,
		&row.TokensUsed,
		&row.CreatedAt,
		&row.UpdatedAt,
		&row.LastActivityAt,
		&row.LatestTaskQuery,
		&row.LatestTaskStatus,
	)
	if err != nil {
		return nil, err
	}
	s.cacheSetJSON(ctx, cacheKey, row)
	s.touchSessionActivity(ctx, sessionID, userID)
	return row, nil
}

func (s *SessionStore) ListSessions(ctx context.Context, userID string, limit, offset int) ([]SessionRow, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	var total int
	if err := s.pg.QueryRow(ctx, `SELECT COUNT(*) FROM kc_sessions WHERE user_id = $1`, userID).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
        SELECT session_id, user_id, title, pinned, task_count, tokens_used, created_at, updated_at, last_activity_at, latest_task_query, latest_task_status
        FROM kc_sessions
        WHERE user_id = $1
        ORDER BY pinned DESC, updated_at DESC NULLS LAST
        LIMIT $2 OFFSET $3
    `, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	sessions := make([]SessionRow, 0)
	for rows.Next() {
		row := SessionRow{}
		if err := rows.Scan(
			&row.SessionID,
			&row.UserID,
			&row.Title,
			&row.Pinned,
			&row.TaskCount,
			&row.TokensUsed,
			&row.CreatedAt,
			&row.UpdatedAt,
			&row.LastActivityAt,
			&row.LatestTaskQuery,
			&row.LatestTaskStatus,
		); err != nil {
			return nil, 0, err
		}
		sessions = append(sessions, row)
	}
	return sessions, total, rows.Err()
}

func (s *SessionStore) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	setParts := []string{}
	args := []any{sessionID, userID}
	argPos := 3
	if title != nil {
		setParts = append(setParts, "title = $"+strconv.Itoa(argPos))
		args = append(args, title)
		argPos++
	}
	if pinned != nil {
		setParts = append(setParts, "pinned = $"+strconv.Itoa(argPos))
		args = append(args, pinned)
		argPos++
	}
	if len(setParts) == 0 {
		return nil
	}
	setParts = append(setParts, "updated_at = NOW()")
	query := "UPDATE kc_sessions SET " + strings.Join(setParts, ", ") + " WHERE session_id = $1 AND user_id = $2"
	_, err := s.pg.Exec(ctx, query, args...)
	if err == nil {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	if s == nil || s.pg == nil {
		return 0, fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `DELETE FROM kc_sessions WHERE session_id = $1 AND user_id = $2`, sessionID, userID)
	if err != nil {
		return 0, err
	}
	s.invalidateSessionCache(ctx, sessionID, userID)
	s.deleteWorkspace(ctx, sessionID)
	return cmd.RowsAffected(), nil
}

func (s *SessionStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]TaskRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	cacheKey := redissvc.SessionCacheKey(userID, sessionID, "history")
	var cached []TaskRow
	if s.cacheGetJSON(ctx, cacheKey, &cached) {
		return cached, nil
	}
	rows, err := s.pg.Query(ctx, `
        SELECT task_id, task_id AS workflow_id, query, status, task_type, result, error_message, created_at, completed_at
        FROM kc_tasks
        WHERE session_id = $1 AND user_id = $2
        ORDER BY created_at ASC
    `, sessionID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	tasks := make([]TaskRow, 0)
	for rows.Next() {
		row := TaskRow{}
		if err := rows.Scan(
			&row.TaskID,
			&row.WorkflowID,
			&row.Query,
			&row.Status,
			&row.TaskType,
			&row.Result,
			&row.Error,
			&row.StartedAt,
			&row.CompletedAt,
		); err != nil {
			return nil, err
		}
		if row.StartedAt != nil && row.CompletedAt != nil {
			d := row.CompletedAt.Sub(*row.StartedAt).Milliseconds()
			row.DurationMS = &d
		}
		tasks = append(tasks, row)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	s.cacheSetJSON(ctx, cacheKey, tasks)
	s.touchSessionActivity(ctx, sessionID, userID)
	return tasks, nil
}

func (s *SessionStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	var payloadJSON any = nil
	if payload != "" {
		payloadJSON = payload
	}
	_, err := s.pg.Exec(ctx, `
	        INSERT INTO kc_events (session_id, task_id, workflow_id, event_type, message, payload, stream_id, created_at)
	        SELECT $1::varchar, $2::varchar, $3::varchar, $4::varchar, $5::text, $6::jsonb, $7::varchar, $8::timestamptz
	        WHERE COALESCE($7::varchar, '') = '' OR NOT EXISTS (
	            SELECT 1 FROM kc_events
	            WHERE task_id = $2::varchar
	              AND event_type = $4::varchar
	              AND stream_id = $7::varchar
	        )
	    `, sessionID, taskID, workflowID, eventType, message, payloadJSON, streamID, ts)
	if err == nil {
		_, _ = s.pg.Exec(ctx, `
            UPDATE kc_sessions
            SET last_activity_at = $2,
                updated_at = $2,
                latest_task_status = $3
            WHERE session_id = $1
        `, sessionID, ts.UTC(), eventType)
		s.invalidateSessionCache(ctx, sessionID, "")
	}
	return err
}

func (s *SessionStore) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]EventRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, `
        SELECT id, task_id, workflow_id, event_type, message, payload::text, stream_id, created_at
        FROM kc_events
        WHERE session_id = $1
        ORDER BY id ASC
        LIMIT $2 OFFSET $3
    `, sessionID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]EventRow, 0)
	for rows.Next() {
		row := EventRow{}
		if err := rows.Scan(
			&row.ID,
			&row.TaskID,
			&row.Workflow,
			&row.Type,
			&row.Message,
			&row.Payload,
			&row.StreamID,
			&row.Timestamp,
		); err != nil {
			return nil, err
		}
		events = append(events, row)
	}
	return events, rows.Err()
}

func (s *SessionStore) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]EventRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, `
        SELECT id, task_id, workflow_id, event_type, message, payload::text, stream_id, created_at
        FROM kc_events
        WHERE workflow_id = $1
        ORDER BY id ASC
        LIMIT $2 OFFSET $3
    `, workflowID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]EventRow, 0)
	for rows.Next() {
		row := EventRow{}
		if err := rows.Scan(
			&row.ID,
			&row.TaskID,
			&row.Workflow,
			&row.Type,
			&row.Message,
			&row.Payload,
			&row.StreamID,
			&row.Timestamp,
		); err != nil {
			return nil, err
		}
		events = append(events, row)
	}
	return events, rows.Err()
}

func (s *SessionStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	if s == nil || s.redisSvc == nil {
		return nil, fmt.Errorf("redis not configured")
	}
	out := map[string]any{}
	ok, err := s.redisSvc.GetJSON(ctx, redissvc.SessionWorkspaceKey(sessionID), &out)
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
	if s == nil || s.redisSvc == nil {
		return fmt.Errorf("redis not configured")
	}
	if strings.TrimSpace(sessionID) == "" {
		return fmt.Errorf("session_id is required")
	}
	if workspace == nil {
		workspace = map[string]any{}
	}
	workspace["session_id"] = sessionID
	return s.redisSvc.SetJSON(ctx, redissvc.SessionWorkspaceKey(sessionID), workspace, 0)
}

func (s *SessionStore) deleteWorkspace(ctx context.Context, sessionID string) {
	if s == nil || s.redisSvc == nil {
		return
	}
	_ = s.redisSvc.Del(ctx, redissvc.SessionWorkspaceKey(sessionID))
}

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
