// Package repo implements application outer layer contracts.
package repo

import (
	"context"
	"time"

	"task-orchestrator/internal/entity"
)

type (
	TaskFilter struct {
		UserID string
		Limit  int
		Offset int
	}

	TaskRepo interface {
		GetByID(ctx context.Context, id entity.TaskID) (*entity.Task, error)
		Save(ctx context.Context, aggregate *entity.Task) error
		List(ctx context.Context, filter TaskFilter) ([]*entity.Task, int, error)
	}

	EventPublisher interface {
		Publish(ctx context.Context, events []entity.DomainEvent) error
	}

	WorkflowOutboxEvent struct {
		TaskID     string
		SessionID  string
		UserID     string
		WorkflowID string
		RunID      string
		EventType  string
		Channel    string
		Payload    map[string]any
		OccurredAt time.Time
	}
)
