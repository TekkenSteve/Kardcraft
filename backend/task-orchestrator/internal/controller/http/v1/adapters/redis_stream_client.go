package adapters

import (
	"context"
	"time"

	v1stream "task-orchestrator/internal/controller/http/v1/stream"
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

func (c *RedisStreamClient) StreamRead(
	ctx context.Context,
	workflowID,
	fromID string,
	count int64,
	block time.Duration,
) ([]v1stream.Entry, string, error) {
	rows, nextID, err := c.svc.StreamRead(ctx, workflowID, fromID, count, block)
	if err != nil {
		return nil, nextID, err
	}
	out := make([]v1stream.Entry, 0, len(rows))
	for _, row := range rows {
		out = append(out, v1stream.Entry{
			ID:     row.ID,
			Values: row.Values,
		})
	}
	return out, nextID, nil
}

func (c *RedisStreamClient) GetCheckpoint(ctx context.Context, workflowID string) (string, error) {
	return c.svc.GetCheckpoint(ctx, workflowID)
}

func (c *RedisStreamClient) SetCheckpoint(ctx context.Context, workflowID, streamID string) error {
	return c.svc.SetCheckpoint(ctx, workflowID, streamID)
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
