package redis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
	"time"

	goredis "github.com/redis/go-redis/v9"
)

const checkpointPrefix = "stream:checkpoint:"

type Service struct {
	client *goredis.Client

	readCalls           atomic.Uint64
	readErrors          atomic.Uint64
	totalReadLatencyNS  atomic.Uint64
	lastReadLatencyNS   atomic.Uint64
	checkpointGetCalls  atomic.Uint64
	checkpointSetCalls  atomic.Uint64
	lastCheckpointSetNS atomic.Int64
}

type StreamEntry struct {
	ID     string
	Values map[string]any
}

type Stats struct {
	ReadCalls            uint64  `json:"read_calls"`
	ReadErrors           uint64  `json:"read_errors"`
	AverageReadLatencyMS float64 `json:"avg_read_latency_ms"`
	LastReadLatencyMS    float64 `json:"last_read_latency_ms"`
	CheckpointGetCalls   uint64  `json:"checkpoint_get_calls"`
	CheckpointSetCalls   uint64  `json:"checkpoint_set_calls"`
	LastCheckpointSetAt  string  `json:"last_checkpoint_set_at,omitempty"`
	CheckpointLagSeconds int64   `json:"checkpoint_lag_seconds"`
}

func NewService(client *goredis.Client) *Service {
	return &Service{client: client}
}

func (s *Service) Enabled() bool {
	return s != nil && s.client != nil
}

func StreamKey(workflowID string) string {
	return "stream:events:" + strings.TrimSpace(workflowID)
}

func TaskSessionKey(taskID string) string {
	return "task:session:" + strings.TrimSpace(taskID)
}

func SessionWorkspaceKey(sessionID string) string {
	return "pack:session:" + strings.TrimSpace(sessionID)
}

func SessionCacheKey(userID, sessionID, suffix string) string {
	return "sess:" + strings.TrimSpace(userID) + ":" + strings.TrimSpace(sessionID) + ":" + strings.TrimSpace(suffix)
}

func SessionCachePattern(sessionID, suffix string) string {
	return "sess:*:" + strings.TrimSpace(sessionID) + ":" + strings.TrimSpace(suffix)
}

func SessionActiveKey(userID, sessionID string) string {
	return SessionCacheKey(userID, sessionID, "active")
}

func checkpointKey(workflowID string) string {
	return checkpointPrefix + strings.TrimSpace(workflowID)
}

func (s *Service) StreamRead(
	ctx context.Context,
	workflowID string,
	fromID string,
	count int64,
	block time.Duration,
) ([]StreamEntry, string, error) {
	if !s.Enabled() {
		return nil, "", errors.New("redis service disabled")
	}
	start := time.Now()
	s.readCalls.Add(1)
	key := StreamKey(workflowID)
	result, err := s.client.XRead(ctx, &goredis.XReadArgs{
		Streams: []string{key, fromID},
		Count:   count,
		Block:   block,
	}).Result()
	latencyNS := uint64(time.Since(start).Nanoseconds())
	s.lastReadLatencyNS.Store(latencyNS)
	s.totalReadLatencyNS.Add(latencyNS)
	if err != nil {
		s.readErrors.Add(1)
		return nil, fromID, err
	}
	entries := make([]StreamEntry, 0, 16)
	lastID := fromID
	for _, stream := range result {
		for _, msg := range stream.Messages {
			lastID = msg.ID
			entries = append(entries, StreamEntry{
				ID:     msg.ID,
				Values: msg.Values,
			})
		}
	}
	return entries, lastID, nil
}

func (s *Service) StreamAppend(ctx context.Context, workflowID string, values map[string]any, maxLen int64) (string, error) {
	if !s.Enabled() {
		return "", errors.New("redis service disabled")
	}
	key := StreamKey(workflowID)
	args := &goredis.XAddArgs{
		Stream: key,
		Values: values,
	}
	if maxLen > 0 {
		args.MaxLen = maxLen
		args.Approx = true
	}
	return s.client.XAdd(ctx, args).Result()
}

func (s *Service) GetString(ctx context.Context, key string) (string, error) {
	if !s.Enabled() {
		return "", errors.New("redis service disabled")
	}
	return s.client.Get(ctx, key).Result()
}

func (s *Service) SetString(ctx context.Context, key, value string, ttl time.Duration) error {
	if !s.Enabled() {
		return errors.New("redis service disabled")
	}
	return s.client.Set(ctx, key, value, ttl).Err()
}

func (s *Service) Del(ctx context.Context, keys ...string) error {
	if !s.Enabled() || len(keys) == 0 {
		return nil
	}
	return s.client.Del(ctx, keys...).Err()
}

func (s *Service) GetJSON(ctx context.Context, key string, out any) (bool, error) {
	raw, err := s.GetString(ctx, key)
	if err != nil {
		if errors.Is(err, goredis.Nil) {
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

func (s *Service) SetJSON(ctx context.Context, key string, val any, ttl time.Duration) error {
	if !s.Enabled() {
		return errors.New("redis service disabled")
	}
	b, err := json.Marshal(val)
	if err != nil {
		return err
	}
	return s.SetString(ctx, key, string(b), ttl)
}

func (s *Service) DeleteByPattern(ctx context.Context, pattern string, scanCount int64) error {
	if !s.Enabled() {
		return errors.New("redis service disabled")
	}
	if scanCount <= 0 {
		scanCount = 100
	}
	var cursor uint64
	for {
		keys, next, err := s.client.Scan(ctx, cursor, pattern, scanCount).Result()
		if err != nil {
			return err
		}
		if len(keys) > 0 {
			if err := s.client.Del(ctx, keys...).Err(); err != nil {
				return err
			}
		}
		cursor = next
		if cursor == 0 {
			break
		}
	}
	return nil
}

func (s *Service) SetCheckpoint(ctx context.Context, workflowID, streamID string) error {
	if !s.Enabled() {
		return nil
	}
	if strings.TrimSpace(workflowID) == "" || strings.TrimSpace(streamID) == "" {
		return nil
	}
	s.checkpointSetCalls.Add(1)
	s.lastCheckpointSetNS.Store(time.Now().UTC().UnixNano())
	return s.client.Set(ctx, checkpointKey(workflowID), streamID, 0).Err()
}

func (s *Service) GetCheckpoint(ctx context.Context, workflowID string) (string, error) {
	if !s.Enabled() {
		return "", nil
	}
	s.checkpointGetCalls.Add(1)
	id, err := s.client.Get(ctx, checkpointKey(workflowID)).Result()
	if err == nil {
		return strings.TrimSpace(id), nil
	}
	if errors.Is(err, goredis.Nil) {
		return "", nil
	}
	return "", fmt.Errorf("get checkpoint: %w", err)
}

func (s *Service) Stats() Stats {
	if s == nil {
		return Stats{}
	}
	readCalls := s.readCalls.Load()
	totalLatencyNS := s.totalReadLatencyNS.Load()
	avgLatency := 0.0
	if readCalls > 0 {
		avgLatency = (float64(totalLatencyNS) / float64(readCalls)) / 1e6
	}
	lastSetNS := s.lastCheckpointSetNS.Load()
	lastSetAt := ""
	lagSeconds := int64(0)
	if lastSetNS > 0 {
		lastSetTime := time.Unix(0, lastSetNS).UTC()
		lastSetAt = lastSetTime.Format(time.RFC3339Nano)
		lagSeconds = int64(time.Since(lastSetTime).Seconds())
		if lagSeconds < 0 {
			lagSeconds = 0
		}
	}
	return Stats{
		ReadCalls:            readCalls,
		ReadErrors:           s.readErrors.Load(),
		AverageReadLatencyMS: avgLatency,
		LastReadLatencyMS:    float64(s.lastReadLatencyNS.Load()) / 1e6,
		CheckpointGetCalls:   s.checkpointGetCalls.Load(),
		CheckpointSetCalls:   s.checkpointSetCalls.Load(),
		LastCheckpointSetAt:  lastSetAt,
		CheckpointLagSeconds: lagSeconds,
	}
}
