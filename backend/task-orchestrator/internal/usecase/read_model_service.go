package usecase

import (
	"context"
	"time"

	"task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

type SessionRow = dto.SessionRow
type TaskRow = dto.TaskRow
type EventRow = dto.EventRow
type ModelUsageBreakdown = dto.ModelUsageBreakdown
type TaskUsageSummary = dto.TaskUsageSummary
type TemplateCatalogRow = dto.TemplateCatalogRow
type UsageLedgerRow = dto.UsageLedgerRow

type ReadModelService struct {
	store port.ReadModelStore
}

func NewReadModelService(store port.ReadModelStore) *ReadModelService {
	return &ReadModelService{store: store}
}

func (s *ReadModelService) Ready() bool { return s != nil && s.store != nil && s.store.Ready() }
func (s *ReadModelService) ListSessions(ctx context.Context, userID string, limit, offset int) ([]SessionRow, int, error) {
	return s.store.ListSessions(ctx, userID, limit, offset)
}
func (s *ReadModelService) GetSession(ctx context.Context, sessionID, userID string) (*SessionRow, error) {
	return s.store.GetSession(ctx, sessionID, userID)
}
func (s *ReadModelService) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	return s.store.UpdateSessionMeta(ctx, sessionID, userID, title, pinned)
}
func (s *ReadModelService) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	return s.store.DeleteSession(ctx, sessionID, userID)
}
func (s *ReadModelService) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]TaskRow, error) {
	return s.store.ListSessionTasks(ctx, sessionID, userID)
}
func (s *ReadModelService) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]EventRow, error) {
	return s.store.ListSessionEvents(ctx, sessionID, limit, offset)
}
func (s *ReadModelService) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]EventRow, error) {
	return s.store.ListWorkflowEvents(ctx, workflowID, limit, offset)
}
func (s *ReadModelService) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	return s.store.LoadWorkspace(ctx, sessionID)
}
func (s *ReadModelService) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	return s.store.SaveWorkspace(ctx, sessionID, workspace)
}
func (s *ReadModelService) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	return s.store.MarkSessionActive(ctx, sessionID, userID)
}
func (s *ReadModelService) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return s.store.GetTaskSession(ctx, taskID)
}
func (s *ReadModelService) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return s.store.UpdateTaskStatus(ctx, taskID, status, errMsg)
}
func (s *ReadModelService) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]TaskUsageSummary, error) {
	return s.store.GetTaskUsageSummaryMapBySession(ctx, sessionID, userID)
}
func (s *ReadModelService) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]TaskUsageSummary, error) {
	return s.store.GetTaskUsageSummaryMapByTaskIDs(ctx, userID, taskIDs)
}
func (s *ReadModelService) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]TemplateCatalogRow, int, error) {
	return s.store.ListAccessibleTemplates(ctx, userID, limit, offset)
}
func (s *ReadModelService) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*TemplateCatalogRow, error) {
	return s.store.GetAccessibleTemplate(ctx, userID, templateID)
}
func (s *ReadModelService) GetUserTemplatePreference(ctx context.Context, userID string) (*TemplateCatalogRow, error) {
	return s.store.GetUserTemplatePreference(ctx, userID)
}
func (s *ReadModelService) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	return s.store.UpsertUserTemplatePreference(ctx, userID, templateID, version)
}
func (s *ReadModelService) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	return s.store.InsertEvent(ctx, sessionID, taskID, workflowID, eventType, message, payload, streamID, ts)
}
func (s *ReadModelService) InsertLLMUsage(ctx context.Context, row UsageLedgerRow) (bool, error) {
	return s.store.InsertLLMUsage(ctx, row)
}
