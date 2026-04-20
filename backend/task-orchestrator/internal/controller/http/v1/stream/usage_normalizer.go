package stream

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

type Entry struct {
	ID     string
	Values map[string]any
}

type UsageRecordPayload struct {
	IdempotencyKey   string         `json:"idempotency_key"`
	Operation        string         `json:"operation"`
	Intent           string         `json:"intent"`
	Provider         string         `json:"provider"`
	Model            string         `json:"model"`
	PromptTokens     int            `json:"prompt_tokens"`
	CompletionTokens int            `json:"completion_tokens"`
	CacheReadTokens  int            `json:"cache_read_tokens"`
	CacheWriteTokens int            `json:"cache_write_tokens"`
	TotalTokens      int            `json:"total_tokens"`
	InputCostUSD     float64        `json:"input_cost_usd"`
	OutputCostUSD    float64        `json:"output_cost_usd"`
	CacheCostUSD     float64        `json:"cache_cost_usd"`
	TotalCostUSD     float64        `json:"total_cost_usd"`
	Estimated        bool           `json:"estimated"`
	Source           string         `json:"source"`
	ExternalRequest  string         `json:"external_request_id"`
	CreatedAt        string         `json:"created_at"`
	Metadata         map[string]any `json:"metadata,omitempty"`
}

type UsageEnvelopePayload struct {
	EventID    string             `json:"event_id"`
	OccurredAt string             `json:"occurred_at"`
	EventType  string             `json:"event_type,omitempty"`
	Message    string             `json:"message,omitempty"`
	Workspace  string             `json:"workspace_id,omitempty"`
	TaskID     string             `json:"task_id"`
	WorkflowID string             `json:"workflow_id"`
	SessionID  string             `json:"session_id"`
	UserID     string             `json:"user_id"`
	Usage      UsageRecordPayload `json:"usage"`
}

func decodeUsageEnvelope(payload map[string]any) (UsageEnvelopePayload, bool, string) {
	rawUsage, hasUsage := payload["usage"]
	if !hasUsage {
		return UsageEnvelopePayload{}, false, "missing_usage_payload"
	}
	if _, ok := rawUsage.(map[string]any); !ok {
		return UsageEnvelopePayload{}, false, "invalid_usage_type"
	}

	raw, err := json.Marshal(payload)
	if err != nil {
		return UsageEnvelopePayload{}, false, "invalid_payload_encoding"
	}
	var envelope UsageEnvelopePayload
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(&envelope); err != nil {
		return UsageEnvelopePayload{}, false, "invalid_payload_shape"
	}
	if strings.TrimSpace(envelope.TaskID) == "" {
		return UsageEnvelopePayload{}, false, "missing_task_id"
	}
	if !hasRFC3339Timestamp(envelope.OccurredAt) {
		return UsageEnvelopePayload{}, false, "invalid_occurred_at"
	}
	if !hasRFC3339Timestamp(envelope.Usage.CreatedAt) {
		return UsageEnvelopePayload{}, false, "invalid_created_at"
	}
	if strings.TrimSpace(envelope.Usage.IdempotencyKey) == "" {
		return UsageEnvelopePayload{}, false, "missing_idempotency_key"
	}
	if strings.TrimSpace(envelope.Usage.Provider) == "" || strings.TrimSpace(envelope.Usage.Model) == "" {
		return UsageEnvelopePayload{}, false, "missing_required_fields"
	}
	if !isValidUSD(envelope.Usage.InputCostUSD) || !isValidUSD(envelope.Usage.OutputCostUSD) || !isValidUSD(envelope.Usage.CacheCostUSD) {
		return UsageEnvelopePayload{}, false, "invalid_cost_components"
	}
	if envelope.Usage.TotalCostUSD <= 0 {
		return UsageEnvelopePayload{}, false, "missing_authoritative_cost"
	}
	if !isValidUSD(envelope.Usage.TotalCostUSD) {
		return UsageEnvelopePayload{}, false, "invalid_total_cost_usd"
	}
	componentSum := normalizeUSD(envelope.Usage.InputCostUSD + envelope.Usage.OutputCostUSD + envelope.Usage.CacheCostUSD)
	if componentSum > normalizeUSD(envelope.Usage.TotalCostUSD) {
		return UsageEnvelopePayload{}, false, "invalid_cost_breakdown"
	}
	return envelope, true, ""
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
	envelope, ok, reason := decodeUsageEnvelope(payload)
	if !ok {
		return usecase.UsageLedgerRow{}, false, reason
	}

	usagePayload := envelope.Usage
	row := usecase.UsageLedgerRow{
		SchemaVersion:    "1",
		IdempotencyKey:   normalizedString(usagePayload.IdempotencyKey, ""),
		TaskID:           normalizedString(envelope.TaskID, fallbackTaskID),
		WorkflowID:       normalizedString(envelope.WorkflowID, workflowID),
		SessionID:        normalizedString(envelope.SessionID, fallbackSessionID),
		UserID:           normalizedString(envelope.UserID, ""),
		Intent:           normalizedString(firstAny(usagePayload.Intent, usagePayload.Operation), ""),
		Provider:         normalizedString(usagePayload.Provider, ""),
		Model:            normalizedString(usagePayload.Model, ""),
		PromptTokens:     usagePayload.PromptTokens,
		CompletionTokens: usagePayload.CompletionTokens,
		CacheReadTokens:  usagePayload.CacheReadTokens,
		CacheWriteTokens: usagePayload.CacheWriteTokens,
		TotalTokens:      usagePayload.TotalTokens,
		InputCostUSD:     normalizeUSD(usagePayload.InputCostUSD),
		OutputCostUSD:    normalizeUSD(usagePayload.OutputCostUSD),
		CacheCostUSD:     normalizeUSD(usagePayload.CacheCostUSD),
		TotalCostUSD:     normalizeUSD(usagePayload.TotalCostUSD),
		Estimated:        usagePayload.Estimated,
		Source:           normalizedString(usagePayload.Source, ""),
		ExternalRequestID: normalizedString(
			firstAny(usagePayload.ExternalRequest),
			"",
		),
		Metadata: usagePayload.Metadata,
	}
	if createdAt := normalizedString(firstAny(envelope.OccurredAt, usagePayload.CreatedAt), ""); createdAt != "" {
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

func firstAny(values ...any) any {
	for _, v := range values {
		if strings.TrimSpace(ValueAsString(v)) != "" {
			return v
		}
	}
	return nil
}

func hasRFC3339Timestamp(v string) bool {
	s := strings.TrimSpace(v)
	if s == "" {
		return false
	}
	_, err := time.Parse(time.RFC3339Nano, s)
	return err == nil
}

func isValidUSD(v float64) bool {
	return !math.IsNaN(v) && !math.IsInf(v, 0) && v >= 0
}

func normalizeUSD(v float64) float64 {
	return math.Round(v*1e8) / 1e8
}
