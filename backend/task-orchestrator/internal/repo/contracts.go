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

	AgentRunRoute struct {
		RunID          string
		PlanID         string
		NodeID         string
		ThreadID       string
		AccountID      string
		ProjectID      string
		BackendKind    string
		BackendName    string
		IdempotencyKey string
		LifecycleState string
		CreatedAt      time.Time
		UpdatedAt      time.Time
	}

	AgentRunRouteStore interface {
		BindAgentRunRoute(ctx context.Context, route AgentRunRoute) error
		ResolveAgentRunRoute(ctx context.Context, runID string) (AgentRunRoute, bool, error)
		GetAgentRunRoute(ctx context.Context, runID string) (AgentRunRoute, bool, error)
	}
)
