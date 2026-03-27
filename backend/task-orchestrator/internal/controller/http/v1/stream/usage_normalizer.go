package stream

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

const usageSchemaVersion = "1"

type Entry struct {
	ID     string
	Values map[string]any
}

func ValueAsString(v any) string {
	if v == nil {
		return ""
	}
	switch typed := v.(type) {
	case string:
		return strings.TrimSpace(typed)
	case []byte:
		return strings.TrimSpace(string(typed))
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", typed))
	}
}

func BuildUsageLedgerRow(payload map[string]any, workflowID, fallbackTaskID, fallbackSessionID string) (usecase.UsageLedgerRow, bool, string) {
	row := usecase.UsageLedgerRow{
		SchemaVersion:    normalizedString(payload["schema_version"], "1"),
		IdempotencyKey:   normalizedString(payload["idempotency_key"], ""),
		TaskID:           normalizedString(payload["task_id"], fallbackTaskID),
		WorkflowID:       normalizedString(payload["workflow_id"], workflowID),
		SessionID:        normalizedString(payload["session_id"], fallbackSessionID),
		UserID:           normalizedString(payload["user_id"], ""),
		Intent:           normalizedString(payload["intent"], ""),
		Provider:         normalizedString(payload["provider"], ""),
		Model:            normalizedString(payload["model"], ""),
		PromptTokens:     asInt(payload["prompt_tokens"]),
		CompletionTokens: asInt(payload["completion_tokens"]),
		CacheReadTokens:  asInt(payload["cache_read_tokens"]),
		CacheWriteTokens: asInt(payload["cache_write_tokens"]),
		TotalTokens:      asInt(payload["total_tokens"]),
		InputCostUSD:     asFloat(payload["input_cost_usd"]),
		OutputCostUSD:    asFloat(payload["output_cost_usd"]),
		CacheCostUSD:     asFloat(payload["cache_cost_usd"]),
		TotalCostUSD:     asFloat(payload["total_cost_usd"]),
		Estimated:        asBool(payload["estimated"]),
		Source:           normalizedString(payload["source"], ""),
		ExternalRequestID: normalizedString(
			firstAny(payload["external_request_id"], payload["request_id"], payload["llm_response_id"]),
			"",
		),
		Metadata: asMap(payload["metadata"]),
	}
	if row.SchemaVersion != usageSchemaVersion {
		return usecase.UsageLedgerRow{}, false, "schema_mismatch"
	}
	if createdAt := normalizedString(payload["created_at"], ""); createdAt != "" {
		if parsed, err := time.Parse(time.RFC3339Nano, createdAt); err == nil {
			row.CreatedAt = parsed
		}
	}
	if row.IdempotencyKey == "" {
		row.IdempotencyKey = normalizedString(payload["stream_id"], "")
	}
	if row.IdempotencyKey == "" && row.ExternalRequestID != "" && row.TaskID != "" {
		row.IdempotencyKey = row.TaskID + ":" + row.ExternalRequestID
	}
	if row.IdempotencyKey == "" {
		return usecase.UsageLedgerRow{}, false, "missing_idempotency_key"
	}
	if row.TaskID == "" || row.Provider == "" || row.Model == "" {
		return usecase.UsageLedgerRow{}, false, "missing_required_fields"
	}
	if row.TotalTokens == 0 {
		row.TotalTokens = row.PromptTokens + row.CompletionTokens
	}
	return row, true, ""
}

func normalizedString(v any, fallback string) string {
	s := strings.TrimSpace(ValueAsString(v))
	if s == "" {
		return fallback
	}
	return s
}

func asMap(v any) map[string]any {
	if v == nil {
		return nil
	}
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

func asInt(v any) int {
	switch t := v.(type) {
	case int:
		return t
	case int32:
		return int(t)
	case int64:
		return int(t)
	case float32:
		return int(t)
	case float64:
		return int(t)
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return int(i)
		}
	case string:
		if n, err := strconv.Atoi(strings.TrimSpace(t)); err == nil {
			return n
		}
	}
	return 0
}

func asFloat(v any) float64 {
	switch t := v.(type) {
	case float64:
		return t
	case float32:
		return float64(t)
	case int:
		return float64(t)
	case int64:
		return float64(t)
	case json.Number:
		if f, err := t.Float64(); err == nil {
			return f
		}
	case string:
		if f, err := strconv.ParseFloat(strings.TrimSpace(t), 64); err == nil {
			return f
		}
	}
	return 0
}

func asBool(v any) bool {
	switch t := v.(type) {
	case bool:
		return t
	case string:
		b, err := strconv.ParseBool(strings.TrimSpace(t))
		return err == nil && b
	case int:
		return t != 0
	case float64:
		return t != 0
	default:
		return false
	}
}

func firstAny(values ...any) any {
	for _, v := range values {
		if strings.TrimSpace(ValueAsString(v)) != "" {
			return v
		}
	}
	return nil
}
