package persistence

import (
	"context"
	"time"

	"task-orchestrator/internal/usecase/dto"
)

type UsecaseReadModelStore struct {
	store *SessionStore
}

func NewUsecaseReadModelStore(store *SessionStore) *UsecaseReadModelStore {
	return &UsecaseReadModelStore{store: store}
}

func (s *UsecaseReadModelStore) Ready() bool {
	return s != nil && s.store != nil && s.store.Ready()
}

func (s *UsecaseReadModelStore) ListSessions(ctx context.Context, userID string, limit, offset int) ([]dto.SessionRow, int, error) {
	rows, total, err := s.store.ListSessions(ctx, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	out := make([]dto.SessionRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, convertSessionRow(row))
	}
	return out, total, nil
}

func (s *UsecaseReadModelStore) GetSession(ctx context.Context, sessionID, userID string) (*dto.SessionRow, error) {
	row, err := s.store.GetSession(ctx, sessionID, userID)
	if err != nil || row == nil {
		return nil, err
	}
	converted := convertSessionRow(*row)
	return &converted, nil
}

func (s *UsecaseReadModelStore) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	return s.store.UpdateSessionMeta(ctx, sessionID, userID, title, pinned)
}

func (s *UsecaseReadModelStore) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	return s.store.DeleteSession(ctx, sessionID, userID)
}

func (s *UsecaseReadModelStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]dto.TaskRow, error) {
	rows, err := s.store.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	out := make([]dto.TaskRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, convertTaskRow(row))
	}
	return out, nil
}

func (s *UsecaseReadModelStore) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]dto.EventRow, error) {
	rows, err := s.store.ListSessionEvents(ctx, sessionID, limit, offset)
	if err != nil {
		return nil, err
	}
	out := make([]dto.EventRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, convertEventRow(row))
	}
	return out, nil
}

func (s *UsecaseReadModelStore) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]dto.EventRow, error) {
	rows, err := s.store.ListWorkflowEvents(ctx, workflowID, limit, offset)
	if err != nil {
		return nil, err
	}
	out := make([]dto.EventRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, convertEventRow(row))
	}
	return out, nil
}

func (s *UsecaseReadModelStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	return s.store.LoadWorkspace(ctx, sessionID)
}

func (s *UsecaseReadModelStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	return s.store.SaveWorkspace(ctx, sessionID, workspace)
}

func (s *UsecaseReadModelStore) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	return s.store.MarkSessionActive(ctx, sessionID, userID)
}

func (s *UsecaseReadModelStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return s.store.GetTaskSession(ctx, taskID)
}

func (s *UsecaseReadModelStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return s.store.UpdateTaskStatus(ctx, taskID, status, errMsg)
}

func (s *UsecaseReadModelStore) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]dto.TaskUsageSummary, error) {
	rows, err := s.store.GetTaskUsageSummaryMapBySession(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	return convertUsageSummaryMap(rows), nil
}

func (s *UsecaseReadModelStore) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]dto.TaskUsageSummary, error) {
	rows, err := s.store.GetTaskUsageSummaryMapByTaskIDs(ctx, userID, taskIDs)
	if err != nil {
		return nil, err
	}
	return convertUsageSummaryMap(rows), nil
}

func (s *UsecaseReadModelStore) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]dto.TemplateCatalogRow, int, error) {
	rows, total, err := s.store.ListAccessibleTemplates(ctx, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	out := make([]dto.TemplateCatalogRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, convertTemplateRow(row))
	}
	return out, total, nil
}

func (s *UsecaseReadModelStore) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*dto.TemplateCatalogRow, error) {
	row, err := s.store.GetAccessibleTemplate(ctx, userID, templateID)
	if err != nil || row == nil {
		return nil, err
	}
	converted := convertTemplateRow(*row)
	return &converted, nil
}

func (s *UsecaseReadModelStore) GetUserTemplatePreference(ctx context.Context, userID string) (*dto.TemplateCatalogRow, error) {
	row, err := s.store.GetUserTemplatePreference(ctx, userID)
	if err != nil || row == nil {
		return nil, err
	}
	converted := convertTemplateRow(*row)
	return &converted, nil
}

func (s *UsecaseReadModelStore) GetResolvedDefaultTemplate(ctx context.Context, userID string) (*dto.TemplateCatalogRow, error) {
	row, err := s.store.GetResolvedDefaultTemplate(ctx, userID)
	if err != nil || row == nil {
		return nil, err
	}
	converted := convertTemplateRow(*row)
	return &converted, nil
}

func (s *UsecaseReadModelStore) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	return s.store.UpsertUserTemplatePreference(ctx, userID, templateID, version)
}

func (s *UsecaseReadModelStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	return s.store.InsertEvent(ctx, sessionID, taskID, workflowID, eventType, message, payload, streamID, ts)
}

func (s *UsecaseReadModelStore) InsertLLMUsage(ctx context.Context, row dto.UsageLedgerRow) (bool, error) {
	return s.store.InsertLLMUsage(ctx, UsageLedgerRow{
		IdempotencyKey:    row.IdempotencyKey,
		SchemaVersion:     row.SchemaVersion,
		TaskID:            row.TaskID,
		WorkflowID:        row.WorkflowID,
		SessionID:         row.SessionID,
		UserID:            row.UserID,
		Intent:            row.Intent,
		Provider:          row.Provider,
		Model:             row.Model,
		PromptTokens:      row.PromptTokens,
		CompletionTokens:  row.CompletionTokens,
		CacheReadTokens:   row.CacheReadTokens,
		CacheWriteTokens:  row.CacheWriteTokens,
		TotalTokens:       row.TotalTokens,
		InputCostUSD:      row.InputCostUSD,
		OutputCostUSD:     row.OutputCostUSD,
		CacheCostUSD:      row.CacheCostUSD,
		TotalCostUSD:      row.TotalCostUSD,
		Estimated:         row.Estimated,
		Source:            row.Source,
		ExternalRequestID: row.ExternalRequestID,
		Metadata:          row.Metadata,
		CreatedAt:         row.CreatedAt,
	})
}

func convertSessionRow(row SessionRow) dto.SessionRow {
	return dto.SessionRow{
		SessionID:        row.SessionID,
		UserID:           row.UserID,
		Title:            row.Title,
		Pinned:           row.Pinned,
		TaskCount:        row.TaskCount,
		TokensUsed:       row.TokensUsed,
		TotalCostUSD:     row.TotalCostUSD,
		CreatedAt:        row.CreatedAt,
		UpdatedAt:        row.UpdatedAt,
		LastActivityAt:   row.LastActivityAt,
		LatestTaskQuery:  row.LatestTaskQuery,
		LatestTaskStatus: row.LatestTaskStatus,
	}
}

func convertTaskRow(row TaskRow) dto.TaskRow {
	return dto.TaskRow{
		TaskID:      row.TaskID,
		WorkflowID:  row.WorkflowID,
		Query:       row.Query,
		Status:      row.Status,
		TaskType:    row.TaskType,
		Result:      row.Result,
		Error:       row.Error,
		StartedAt:   row.StartedAt,
		CompletedAt: row.CompletedAt,
		DurationMS:  row.DurationMS,
	}
}

func convertEventRow(row EventRow) dto.EventRow {
	return dto.EventRow{
		ID:        row.ID,
		TaskID:    row.TaskID,
		Workflow:  row.Workflow,
		Type:      row.Type,
		Message:   row.Message,
		Payload:   row.Payload,
		StreamID:  row.StreamID,
		Timestamp: row.Timestamp,
	}
}

func convertUsageSummaryMap(rows map[string]TaskUsageSummary) map[string]dto.TaskUsageSummary {
	out := make(map[string]dto.TaskUsageSummary, len(rows))
	for taskID, row := range rows {
		breakdown := make([]dto.ModelUsageBreakdown, 0, len(row.ModelBreakdown))
		for _, item := range row.ModelBreakdown {
			breakdown = append(breakdown, dto.ModelUsageBreakdown{
				Model:               item.Model,
				Provider:            item.Provider,
				Executions:          item.Executions,
				Tokens:              item.Tokens,
				CostUSD:             item.CostUSD,
				PromptTokens:        item.PromptTokens,
				CompletionTokens:    item.CompletionTokens,
				CacheReadTokens:     item.CacheReadTokens,
				CacheWriteTokens:    item.CacheWriteTokens,
				EstimatedExecutions: item.EstimatedExecutions,
			})
		}
		out[taskID] = dto.TaskUsageSummary{
			TotalTokens:      row.TotalTokens,
			PromptTokens:     row.PromptTokens,
			CompletionTokens: row.CompletionTokens,
			CacheReadTokens:  row.CacheReadTokens,
			CacheWriteTokens: row.CacheWriteTokens,
			TotalCostUSD:     row.TotalCostUSD,
			ModelBreakdown:   breakdown,
		}
	}
	return out
}

func convertTemplateRow(row TemplateCatalogRow) dto.TemplateCatalogRow {
	return dto.TemplateCatalogRow{
		TemplateID:             row.TemplateID,
		Name:                   row.Name,
		Description:            row.Description,
		Scope:                  row.Scope,
		OwnerUserID:            row.OwnerUserID,
		Status:                 row.Status,
		IsDefault:              row.IsDefault,
		LatestVersion:          row.LatestVersion,
		VersionPublished:       row.VersionPublished,
		CreatedAt:              row.CreatedAt,
		UpdatedAt:              row.UpdatedAt,
		Tags:                   row.Tags,
		Metadata:               row.Metadata,
		FrontHTML:              row.FrontHTML,
		BackHTML:               row.BackHTML,
		CSS:                    row.CSS,
		JS:                     row.JS,
		MappingSpec:            row.MappingSpec,
		DefaultTemplateID:      row.DefaultTemplateID,
		DefaultTemplateVersion: row.DefaultTemplateVersion,
	}
}
