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

	TaskExecutionRoute struct {
		TaskID       string
		PlanID       string
		AccountID    string
		ProjectID    string
		NodeID       string
		BackendRunID string
	}

	TaskExecutionRouteStore interface {
		BindTaskExecutionRoute(ctx context.Context, route TaskExecutionRoute) error
		GetTaskExecutionRoute(ctx context.Context, taskID string) (TaskExecutionRoute, bool, error)
		GetTaskExecutionRouteByBackendRun(ctx context.Context, backendRunID string) (TaskExecutionRoute, bool, error)
		ListActiveTaskExecutionRoutes(ctx context.Context) ([]TaskExecutionRoute, error)
	}

	APKGExport struct {
		ExportID       string
		SessionID      string
		UserID         string
		TemplateID     string
		DeckName       string
		PackageName    string
		Status         string
		ConfirmedCount int
		FileName       string
		FileSize       int64
		APKGBytes      []byte
		ErrorMessage   string
		CreatedAt      time.Time
		UpdatedAt      time.Time
		CompletedAt    *time.Time
	}

	APKGExportStore interface {
		CreateAndEnqueueAPKGExport(ctx context.Context, export APKGExport) error
		CreateAPKGExport(ctx context.Context, export APKGExport) error
		GetAPKGExportByID(ctx context.Context, exportID string) (APKGExport, bool, error)
		GetAPKGExport(ctx context.Context, exportID, sessionID, userID string) (APKGExport, bool, error)
		MarkAPKGExportRunning(ctx context.Context, exportID string) error
		RetryAPKGExport(ctx context.Context, exportID, reason string) error
		CompleteAPKGExport(ctx context.Context, export APKGExport) error
		FailAPKGExport(ctx context.Context, exportID, reason string) error
	}

	// APKGExportJobArgs is the durable queue contract. The worker resolves all
	// business data from the export record so the queue never duplicates it.
	APKGExportJobArgs struct {
		ExportID string `json:"export_id" river:"unique"`
	}
)

func (APKGExportJobArgs) Kind() string { return "kardcraft.apkg_export" }
