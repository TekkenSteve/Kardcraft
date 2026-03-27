package stream

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

type RedisReader interface {
	Enabled() bool
	StreamRead(ctx context.Context, workflowID, fromID string, count int64, block time.Duration) ([]Entry, string, error)
	GetCheckpoint(ctx context.Context, workflowID string) (string, error)
	SetCheckpoint(ctx context.Context, workflowID, streamID string) error
}

type Reader struct {
	client RedisReader
	count  int64
	block  time.Duration
	logf   func(string, ...any)
}

func NewReader(client RedisReader, count int64, block time.Duration, logf func(string, ...any)) *Reader {
	if count <= 0 {
		count = 32
	}
	if block <= 0 {
		block = 5 * time.Second
	}
	return &Reader{
		client: client,
		count:  count,
		block:  block,
		logf:   logf,
	}
}

func (r *Reader) Enabled() bool {
	return r != nil && r.client != nil && r.client.Enabled()
}

func (r *Reader) StartFrom(ctx context.Context, workflowID string) string {
	if !r.Enabled() {
		return "0-0"
	}
	lastID := "0-0"
	if checkpoint, err := r.client.GetCheckpoint(ctx, workflowID); err == nil && checkpoint != "" {
		lastID = checkpoint
	}
	return lastID
}

func (r *Reader) Read(ctx context.Context, workflowID, lastID string) ([]Entry, string, error) {
	if !r.Enabled() {
		return nil, lastID, context.Canceled
	}
	entries, nextID, err := r.client.StreamRead(ctx, workflowID, lastID, r.count, r.block)
	if err != nil {
		if ctx.Err() != nil {
			return nil, lastID, ctx.Err()
		}
		if err == redis.Nil {
			return nil, lastID, nil
		}
		if r.logf != nil {
			r.logf("redis stream read error workflow_id=%s err=%v", workflowID, err)
		}
		time.Sleep(time.Second)
		return nil, lastID, nil
	}
	return entries, nextID, nil
}

func (r *Reader) SaveCheckpoint(ctx context.Context, workflowID, lastID string) {
	if !r.Enabled() || lastID == "" {
		return
	}
	_ = r.client.SetCheckpoint(ctx, workflowID, lastID)
}
