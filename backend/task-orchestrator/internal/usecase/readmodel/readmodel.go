package readmodel

import (
	"context"
	"time"

	"task-orchestrator/internal/usecase"
)

type UseCase struct {
	store usecase.ReadModelStore
}

func New(store usecase.ReadModelStore) *UseCase {
	return &UseCase{store: store}
}

func (s *UseCase) Ready() bool { return s != nil && s.store != nil && s.store.Ready() }
func (s *UseCase) ListSessions(ctx context.Context, userID string, limit, offset int) ([]usecase.SessionRow, int, error) {
	return s.store.ListSessions(ctx, userID, limit, offset)
}
func (s *UseCase) GetSession(ctx context.Context, sessionID, userID string) (*usecase.SessionRow, error) {
	return s.store.GetSession(ctx, sessionID, userID)
}
func (s *UseCase) GetTask(ctx context.Context, taskID, userID string) (*usecase.TaskRow, error) {
	return s.store.GetTask(ctx, taskID, userID)
}
func (s *UseCase) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	return s.store.UpdateSessionMeta(ctx, sessionID, userID, title, pinned)
}
func (s *UseCase) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	return s.store.DeleteSession(ctx, sessionID, userID)
}
func (s *UseCase) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]usecase.TaskRow, error) {
	return s.store.ListSessionTasks(ctx, sessionID, userID)
}
func (s *UseCase) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]usecase.EventRow, error) {
	return s.store.ListSessionEvents(ctx, sessionID, limit, offset)
}
func (s *UseCase) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]usecase.EventRow, error) {
	return s.store.ListWorkflowEvents(ctx, workflowID, limit, offset)
}
func (s *UseCase) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	return s.store.LoadWorkspace(ctx, sessionID)
}
func (s *UseCase) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	return s.store.SaveWorkspace(ctx, sessionID, workspace)
}
func (s *UseCase) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	return s.store.MarkSessionActive(ctx, sessionID, userID)
}
func (s *UseCase) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return s.store.GetTaskSession(ctx, taskID)
}
func (s *UseCase) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return s.store.UpdateTaskStatus(ctx, taskID, status, errMsg)
}
func (s *UseCase) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]usecase.TaskUsageSummary, error) {
	return s.store.GetTaskUsageSummaryMapBySession(ctx, sessionID, userID)
}
func (s *UseCase) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]usecase.TaskUsageSummary, error) {
	return s.store.GetTaskUsageSummaryMapByTaskIDs(ctx, userID, taskIDs)
}
func (s *UseCase) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]usecase.TemplateCatalogRow, int, error) {
	return s.store.ListAccessibleTemplates(ctx, userID, limit, offset)
}
func (s *UseCase) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*usecase.TemplateCatalogRow, error) {
	return s.store.GetAccessibleTemplate(ctx, userID, templateID)
}
func (s *UseCase) GetUserTemplatePreference(ctx context.Context, userID string) (*usecase.TemplateCatalogRow, error) {
	return s.store.GetUserTemplatePreference(ctx, userID)
}
func (s *UseCase) GetResolvedDefaultTemplate(ctx context.Context, userID string) (*usecase.TemplateCatalogRow, error) {
	return s.store.GetResolvedDefaultTemplate(ctx, userID)
}
func (s *UseCase) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	return s.store.UpsertUserTemplatePreference(ctx, userID, templateID, version)
}
func (s *UseCase) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	return s.store.InsertEvent(ctx, sessionID, taskID, workflowID, eventType, message, payload, streamID, ts)
}
func (s *UseCase) InsertLLMUsage(ctx context.Context, row usecase.UsageLedgerRow) (bool, error) {
	return s.store.InsertLLMUsage(ctx, row)
}
