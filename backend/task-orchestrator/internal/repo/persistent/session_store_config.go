package persistent

import (
	"context"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	redissvc "task-orchestrator/internal/repo/redis"
)

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
		rdb, err := redissvc.NewGeneralClient(ctx, cfg.RedisAddr, cfg.RedisPassword, cfg.RedisDB)
		if err != nil {
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
