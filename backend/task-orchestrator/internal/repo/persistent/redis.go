package persistent

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

func (s *SessionStore) redisEnabled() bool {
	return s != nil && s.redis != nil
}

func (s *SessionStore) redisGetString(ctx context.Context, key string) (string, error) {
	if !s.redisEnabled() {
		return "", errors.New("redis not configured")
	}
	return s.redis.Get(ctx, key).Result()
}

func (s *SessionStore) redisSetString(ctx context.Context, key, value string, ttl time.Duration) error {
	if !s.redisEnabled() {
		return errors.New("redis not configured")
	}
	return s.redis.Set(ctx, key, value, ttl).Err()
}

func (s *SessionStore) redisDelete(ctx context.Context, keys ...string) error {
	if !s.redisEnabled() || len(keys) == 0 {
		return nil
	}
	_, err := s.redis.Del(ctx, keys...).Result()
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
		keys, next, err := s.redis.Scan(ctx, cursor, pattern, int64(scanCount)).Result()
		if err != nil {
			return err
		}
		if len(keys) > 0 {
			if _, err := s.redis.Del(ctx, keys...).Result(); err != nil {
				return err
			}
		}
		cursor = next
		if cursor == 0 {
			return nil
		}
	}
}
