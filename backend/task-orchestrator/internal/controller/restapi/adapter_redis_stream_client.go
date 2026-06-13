package restapi

import (
	redissvc "task-orchestrator/internal/repo/redis"
)

type RedisStreamClient struct {
	svc *redissvc.Service
}

func NewRedisStreamClient(svc *redissvc.Service) *RedisStreamClient {
	return &RedisStreamClient{svc: svc}
}

func (c *RedisStreamClient) Enabled() bool {
	return c != nil && c.svc != nil && c.svc.Enabled()
}

func (c *RedisStreamClient) Stats() map[string]any {
	if c == nil || c.svc == nil {
		return map[string]any{}
	}
	stats := c.svc.Stats()
	return map[string]any{
		"read_calls":             stats.ReadCalls,
		"read_errors":            stats.ReadErrors,
		"avg_read_latency_ms":    stats.AverageReadLatencyMS,
		"last_read_latency_ms":   stats.LastReadLatencyMS,
		"checkpoint_get_calls":   stats.CheckpointGetCalls,
		"checkpoint_set_calls":   stats.CheckpointSetCalls,
		"last_checkpoint_set_at": stats.LastCheckpointSetAt,
		"checkpoint_lag_seconds": stats.CheckpointLagSeconds,
	}
}
