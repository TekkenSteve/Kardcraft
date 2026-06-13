package persistent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

func (s *SessionStore) InsertLLMUsage(ctx context.Context, row UsageLedgerRow) (bool, error) {
	if s == nil || s.pg == nil {
		return false, fmt.Errorf("postgres not configured")
	}
	row.IdempotencyKey = strings.TrimSpace(row.IdempotencyKey)
	if row.IdempotencyKey == "" {
		return false, fmt.Errorf("idempotency_key is required")
	}
	row.TaskID = strings.TrimSpace(row.TaskID)
	if row.TaskID == "" {
		return false, fmt.Errorf("task_id is required")
	}
	row.Provider = strings.TrimSpace(row.Provider)
	if row.Provider == "" {
		return false, fmt.Errorf("provider is required")
	}
	row.Model = strings.TrimSpace(row.Model)
	if row.Model == "" {
		return false, fmt.Errorf("model is required")
	}
	if strings.TrimSpace(row.SchemaVersion) == "" {
		row.SchemaVersion = "1"
	}
	if row.TotalTokens <= 0 {
		row.TotalTokens = row.PromptTokens + row.CompletionTokens
	}
	if row.TotalTokens < 0 {
		row.TotalTokens = 0
	}
	if row.PromptTokens < 0 {
		row.PromptTokens = 0
	}
	if row.CompletionTokens < 0 {
		row.CompletionTokens = 0
	}
	if row.CacheReadTokens < 0 {
		row.CacheReadTokens = 0
	}
	if row.CacheWriteTokens < 0 {
		row.CacheWriteTokens = 0
	}
	if row.InputCostUSD < 0 {
		row.InputCostUSD = 0
	}
	if row.OutputCostUSD < 0 {
		row.OutputCostUSD = 0
	}
	if row.CacheCostUSD < 0 {
		row.CacheCostUSD = 0
	}
	if row.TotalCostUSD < 0 {
		row.TotalCostUSD = 0
	}
	if strings.TrimSpace(row.Source) == "" {
		if row.Estimated {
			row.Source = "estimated"
		} else {
			row.Source = "exact"
		}
	}
	if row.CreatedAt.IsZero() {
		row.CreatedAt = time.Now().UTC()
	} else {
		row.CreatedAt = row.CreatedAt.UTC()
	}

	if strings.TrimSpace(row.SessionID) == "" {
		sessionID, err := s.GetTaskSession(ctx, row.TaskID)
		if err != nil {
			return false, fmt.Errorf("resolve session_id by task_id: %w", err)
		}
		row.SessionID = strings.TrimSpace(sessionID)
	}
	if row.SessionID == "" {
		return false, fmt.Errorf("session_id is required")
	}
	if strings.TrimSpace(row.UserID) == "" {
		if err := s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, row.TaskID).Scan(&row.UserID); err != nil {
			return false, fmt.Errorf("resolve user_id by task_id: %w", err)
		}
		row.UserID = strings.TrimSpace(row.UserID)
	}
	if row.UserID == "" {
		return false, fmt.Errorf("user_id is required")
	}

	var metadataJSON any
	if row.Metadata != nil {
		raw, err := json.Marshal(row.Metadata)
		if err != nil {
			return false, fmt.Errorf("marshal llm usage metadata: %w", err)
		}
		metadataJSON = raw
	}

	tag, err := s.pg.Exec(ctx, `
		INSERT INTO kc_llm_usage_ledger (
			idempotency_key,
			schema_version,
			task_id,
			workflow_id,
			session_id,
			user_id,
			intent,
			provider,
			model,
			prompt_tokens,
			completion_tokens,
			cache_read_tokens,
			cache_write_tokens,
			total_tokens,
			input_cost_usd,
			output_cost_usd,
			cache_cost_usd,
			total_cost_usd,
			estimated,
			source,
			external_request_id,
			metadata,
			created_at
		)
		VALUES (
			$1, $2, $3, NULLIF($4, ''), $5, $6, NULLIF($7, ''), $8, $9, $10, $11, $12, $13, $14,
			$15, $16, $17, $18, $19, $20, NULLIF($21, ''), COALESCE($22::jsonb, '{}'::jsonb), $23
		)
		ON CONFLICT (idempotency_key) DO NOTHING
	`,
		row.IdempotencyKey,
		row.SchemaVersion,
		row.TaskID,
		row.WorkflowID,
		row.SessionID,
		row.UserID,
		row.Intent,
		row.Provider,
		row.Model,
		row.PromptTokens,
		row.CompletionTokens,
		row.CacheReadTokens,
		row.CacheWriteTokens,
		row.TotalTokens,
		row.InputCostUSD,
		row.OutputCostUSD,
		row.CacheCostUSD,
		row.TotalCostUSD,
		row.Estimated,
		row.Source,
		row.ExternalRequestID,
		metadataJSON,
		row.CreatedAt,
	)
	if err != nil {
		return false, err
	}
	inserted := tag.RowsAffected() > 0
	if inserted {
		s.invalidateSessionCache(ctx, row.SessionID, row.UserID)
		s.touchSessionActivity(ctx, row.SessionID, row.UserID)
	}
	return inserted, nil
}

func (s *SessionStore) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]TaskUsageSummary, error) {
	return s.getTaskUsageSummaryMap(ctx, `
		SELECT
			task_id,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(total_tokens), 0) AS total_tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
		FROM kc_llm_usage_ledger
		WHERE session_id = $1 AND user_id = $2
		GROUP BY task_id
	`, sessionID, userID)
}

func (s *SessionStore) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]TaskUsageSummary, error) {
	if len(taskIDs) == 0 {
		return map[string]TaskUsageSummary{}, nil
	}
	filtered := make([]string, 0, len(taskIDs))
	for _, id := range taskIDs {
		if strings.TrimSpace(id) != "" {
			filtered = append(filtered, strings.TrimSpace(id))
		}
	}
	if len(filtered) == 0 {
		return map[string]TaskUsageSummary{}, nil
	}
	return s.getTaskUsageSummaryMap(ctx, `
		SELECT
			task_id,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(total_tokens), 0) AS total_tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
		FROM kc_llm_usage_ledger
		WHERE user_id = $1 AND task_id = ANY($2)
		GROUP BY task_id
	`, userID, filtered)
}

func (s *SessionStore) getTaskUsageSummaryMap(ctx context.Context, summaryQuery string, args ...any) (map[string]TaskUsageSummary, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, summaryQuery, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	summary := make(map[string]TaskUsageSummary)
	for rows.Next() {
		var taskID string
		var item TaskUsageSummary
		if err := rows.Scan(
			&taskID,
			&item.PromptTokens,
			&item.CompletionTokens,
			&item.CacheReadTokens,
			&item.CacheWriteTokens,
			&item.TotalTokens,
			&item.TotalCostUSD,
		); err != nil {
			return nil, err
		}
		summary[taskID] = item
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	breakdownRows, err := s.pg.Query(ctx, `
		SELECT
			task_id,
			model,
			provider,
			COUNT(*) AS executions,
			COALESCE(SUM(total_tokens), 0) AS tokens,
			COALESCE(SUM(total_cost_usd::double precision), 0) AS cost_usd,
			COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
			COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
			COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
			COALESCE(SUM(CASE WHEN estimated THEN 1 ELSE 0 END), 0) AS estimated_executions
		FROM kc_llm_usage_ledger
		WHERE task_id = ANY($1)
		GROUP BY task_id, model, provider
		ORDER BY task_id ASC, cost_usd DESC, model ASC
	`, mapsKeys(summary))
	if err != nil {
		return nil, err
	}
	defer breakdownRows.Close()
	for breakdownRows.Next() {
		var taskID string
		entry := ModelUsageBreakdown{}
		if err := breakdownRows.Scan(
			&taskID,
			&entry.Model,
			&entry.Provider,
			&entry.Executions,
			&entry.Tokens,
			&entry.CostUSD,
			&entry.PromptTokens,
			&entry.CompletionTokens,
			&entry.CacheReadTokens,
			&entry.CacheWriteTokens,
			&entry.EstimatedExecutions,
		); err != nil {
			return nil, err
		}
		item := summary[taskID]
		item.ModelBreakdown = append(item.ModelBreakdown, entry)
		summary[taskID] = item
	}
	if err := breakdownRows.Err(); err != nil {
		return nil, err
	}
	return summary, nil
}

func mapsKeys(m map[string]TaskUsageSummary) []string {
	out := make([]string, 0, len(m))
	for key := range m {
		out = append(out, key)
	}
	return out
}
