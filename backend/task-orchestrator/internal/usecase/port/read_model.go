package port

import (
	"context"
	"time"

	"task-orchestrator/internal/usecase/dto"
)

type ReadModelStore interface {
	Ready() bool
	ListSessions(ctx context.Context, userID string, limit, offset int) ([]dto.SessionRow, int, error)
	GetSession(ctx context.Context, sessionID, userID string) (*dto.SessionRow, error)
	UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error
	DeleteSession(ctx context.Context, sessionID, userID string) (int64, error)
	ListSessionTasks(ctx context.Context, sessionID, userID string) ([]dto.TaskRow, error)
	ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]dto.EventRow, error)
	ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]dto.EventRow, error)
	LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error)
	SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error
	MarkSessionActive(ctx context.Context, sessionID, userID string) error
	GetTaskSession(ctx context.Context, taskID string) (string, error)
	UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
	GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]dto.TaskUsageSummary, error)
	GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]dto.TaskUsageSummary, error)
	ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]dto.TemplateCatalogRow, int, error)
	GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*dto.TemplateCatalogRow, error)
	GetUserTemplatePreference(ctx context.Context, userID string) (*dto.TemplateCatalogRow, error)
	UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error
	InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error
	InsertLLMUsage(ctx context.Context, row dto.UsageLedgerRow) (bool, error)
}
