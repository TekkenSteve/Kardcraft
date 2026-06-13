package restapi

import (
	"net/http"
	"time"

	"task-orchestrator/internal/usecase"
)

func handleSessionHistory(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load session history", http.StatusInternalServerError)
		return
	}
	usageByTask, err := deps.ReadModel.GetTaskUsageSummaryMapBySession(r.Context(), sessionID, userID)
	if err != nil {
		http.Error(w, "failed to load usage summary", http.StatusInternalServerError)
		return
	}
	items := make([]map[string]any, 0, len(tasks))
	for _, t := range tasks {
		usage := usageByTask[t.TaskID]
		status, reason := usageProjectionStatus(t, usage, time.Now().UTC())
		metadata, modelUsed, provider := buildUsageMetadata(usage)
		item := map[string]any{
			"task_id":                 t.TaskID,
			"workflow_id":             t.WorkflowID,
			"query":                   valueFromPtr(t.Query),
			"status":                  valueFromPtr(t.Status),
			"mode":                    valueFromPtr(t.TaskType),
			"total_tokens":            usage.TotalTokens,
			"total_cost_usd":          usage.TotalCostUSD,
			"usage_projection_status": status,
			"usage_projection_reason": reason,
		}
		if modelUsed != "" {
			item["model_used"] = modelUsed
		}
		if provider != "" {
			item["provider"] = provider
		}
		if metadata != nil {
			item["metadata"] = metadata
		}
		if t.StartedAt != nil {
			item["started_at"] = t.StartedAt.UTC().Format(time.RFC3339)
		}
		if t.CompletedAt != nil {
			item["completed_at"] = t.CompletedAt.UTC().Format(time.RFC3339)
			if t.DurationMS != nil {
				item["duration_ms"] = *t.DurationMS
			}
		}
		if t.Error != nil {
			item["error_message"] = *t.Error
		}
		items = append(items, item)
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "tasks": items})
}

func usageProjectionStatus(task usecase.TaskRow, usage usecase.TaskUsageSummary, now time.Time) (string, string) {
	if task.CompletedAt == nil {
		return "pending", "task_not_completed"
	}
	hasUsage := usage.TotalTokens > 0 || usage.TotalCostUSD > 0 || len(usage.ModelBreakdown) > 0
	if hasUsage {
		return "finalized", "usage_ingested"
	}
	// Grace window to absorb async projection lag before marking invalid.
	const projectionGrace = 5 * time.Minute
	completedAt := task.CompletedAt.UTC()
	if now.UTC().Sub(completedAt) <= projectionGrace {
		return "partial", "awaiting_usage_projection"
	}
	return "invalid", "usage_missing_after_grace_window"
}

func buildUsageMetadata(usage usecase.TaskUsageSummary) (map[string]any, string, string) {
	if len(usage.ModelBreakdown) == 0 {
		return nil, "", ""
	}
	breakdown := make([]map[string]any, 0, len(usage.ModelBreakdown))
	totalExecutions := 0
	estimatedExecutions := 0
	for _, entry := range usage.ModelBreakdown {
		breakdown = append(breakdown, map[string]any{
			"model":                entry.Model,
			"provider":             entry.Provider,
			"executions":           entry.Executions,
			"tokens":               entry.Tokens,
			"cost_usd":             entry.CostUSD,
			"prompt_tokens":        entry.PromptTokens,
			"completion_tokens":    entry.CompletionTokens,
			"cache_read_tokens":    entry.CacheReadTokens,
			"cache_write_tokens":   entry.CacheWriteTokens,
			"estimated_executions": entry.EstimatedExecutions,
		})
		totalExecutions += entry.Executions
		estimatedExecutions += entry.EstimatedExecutions
	}

	primary := usage.ModelBreakdown[0]
	estimatedRatio := 0.0
	if totalExecutions > 0 {
		estimatedRatio = float64(estimatedExecutions) / float64(totalExecutions)
	}

	metadata := map[string]any{
		"model":           primary.Model,
		"provider":        primary.Provider,
		"model_breakdown": breakdown,
		"usage_quality": map[string]any{
			"has_estimated_usage": estimatedExecutions > 0,
			"estimated_ratio":     estimatedRatio,
		},
	}
	return metadata, primary.Model, primary.Provider
}
