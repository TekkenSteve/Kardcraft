package redis

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	goredis "github.com/redis/go-redis/v9"
)

const (
	defaultGeneralPoolSize       = 200
	defaultStreamPoolSize        = 50
	defaultSocketTimeoutSeconds  = 10.0
	defaultConnectTimeoutSeconds = 5.0
	defaultPingTimeoutSeconds    = 5.0
)

func NewGeneralClient(ctx context.Context, addr, password string, db int) (*goredis.Client, error) {
	opts := baseOptions(addr, password, db, envInt("REDIS_GENERAL_POOL_SIZE", defaultGeneralPoolSize))
	return newCheckedClient(ctx, opts)
}

func NewStreamClient(ctx context.Context, addr, password string, db int) (*goredis.Client, error) {
	opts := baseOptions(addr, password, db, envInt("REDIS_STREAM_POOL_SIZE", defaultStreamPoolSize))
	return newCheckedClient(ctx, opts)
}

func baseOptions(addr, password string, db, poolSize int) *goredis.Options {
	socketTimeout := envDurationSeconds("REDIS_SOCKET_TIMEOUT", defaultSocketTimeoutSeconds)
	connectTimeout := envDurationSeconds("REDIS_SOCKET_CONNECT_TIMEOUT", defaultConnectTimeoutSeconds)
	return &goredis.Options{
		Addr:         strings.TrimSpace(addr),
		Password:     password,
		DB:           db,
		PoolSize:     poolSize,
		ReadTimeout:  socketTimeout,
		WriteTimeout: socketTimeout,
		DialTimeout:  connectTimeout,
		PoolTimeout:  connectTimeout,
	}
}

func newCheckedClient(ctx context.Context, opts *goredis.Options) (*goredis.Client, error) {
	if opts == nil || strings.TrimSpace(opts.Addr) == "" {
		return nil, fmt.Errorf("redis address is required")
	}
	client := goredis.NewClient(opts)
	pingCtx, cancel := context.WithTimeout(ctx, envDurationSeconds("REDIS_PING_TIMEOUT", defaultPingTimeoutSeconds))
	defer cancel()
	if err := client.Ping(pingCtx).Err(); err != nil {
		_ = client.Close()
		return nil, err
	}
	return client, nil
}

func envInt(name string, def int) int {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return def
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value <= 0 {
		return def
	}
	return value
}

func envDurationSeconds(name string, def float64) time.Duration {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return time.Duration(def * float64(time.Second))
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil || value <= 0 {
		return time.Duration(def * float64(time.Second))
	}
	return time.Duration(value * float64(time.Second))
}
