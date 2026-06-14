// Package repo implements application outer layer contracts.
package repo

import (
	"context"

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
)
