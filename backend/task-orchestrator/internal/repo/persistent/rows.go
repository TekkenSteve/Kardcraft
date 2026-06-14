package persistent

import "time"

type SessionRow struct {
	SessionID        string     `json:"session_id"`
	UserID           string     `json:"user_id"`
	Title            *string    `json:"title,omitempty"`
	Pinned           bool       `json:"pinned"`
	TaskCount        int        `json:"task_count"`
	TokensUsed       int        `json:"tokens_used"`
	TotalCostUSD     float64    `json:"total_cost_usd"`
	CreatedAt        time.Time  `json:"created_at"`
	UpdatedAt        time.Time  `json:"updated_at"`
	LastActivityAt   *time.Time `json:"last_activity_at,omitempty"`
	LatestTaskQuery  *string    `json:"latest_task_query,omitempty"`
	LatestTaskStatus *string    `json:"latest_task_status,omitempty"`
}

type TaskRow struct {
	TaskID      string     `json:"task_id"`
	WorkflowID  string     `json:"workflow_id"`
	Query       *string    `json:"query,omitempty"`
	Status      *string    `json:"status,omitempty"`
	TaskType    *string    `json:"mode,omitempty"`
	Result      any        `json:"result,omitempty"`
	Error       *string    `json:"error_message,omitempty"`
	StartedAt   *time.Time `json:"started_at,omitempty"`
	CompletedAt *time.Time `json:"completed_at,omitempty"`
	DurationMS  *int64     `json:"duration_ms,omitempty"`
}

type EventRow struct {
	ID        int64     `json:"seq"`
	TaskID    *string   `json:"task_id,omitempty"`
	Workflow  *string   `json:"workflow_id,omitempty"`
	Type      string    `json:"type"`
	Message   *string   `json:"message,omitempty"`
	Payload   *string   `json:"payload,omitempty"`
	StreamID  *string   `json:"stream_id,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}

type UsageLedgerRow struct {
	IdempotencyKey    string
	SchemaVersion     string
	TaskID            string
	WorkflowID        string
	SessionID         string
	UserID            string
	Intent            string
	Provider          string
	Model             string
	PromptTokens      int
	CompletionTokens  int
	CacheReadTokens   int
	CacheWriteTokens  int
	TotalTokens       int
	InputCostUSD      float64
	OutputCostUSD     float64
	CacheCostUSD      float64
	TotalCostUSD      float64
	Estimated         bool
	Source            string
	ExternalRequestID string
	Metadata          map[string]any
	CreatedAt         time.Time
}

type ModelUsageBreakdown struct {
	Model               string  `json:"model"`
	Provider            string  `json:"provider"`
	Executions          int     `json:"executions"`
	Tokens              int     `json:"tokens"`
	CostUSD             float64 `json:"cost_usd"`
	PromptTokens        int     `json:"prompt_tokens"`
	CompletionTokens    int     `json:"completion_tokens"`
	CacheReadTokens     int     `json:"cache_read_tokens"`
	CacheWriteTokens    int     `json:"cache_write_tokens"`
	EstimatedExecutions int     `json:"estimated_executions"`
}

type TaskUsageSummary struct {
	TotalTokens      int
	PromptTokens     int
	CompletionTokens int
	CacheReadTokens  int
	CacheWriteTokens int
	TotalCostUSD     float64
	ModelBreakdown   []ModelUsageBreakdown
}

type TemplateCatalogRow struct {
	TemplateID             string         `json:"template_id"`
	Name                   string         `json:"name"`
	Description            string         `json:"description,omitempty"`
	Scope                  string         `json:"scope"`
	OwnerUserID            string         `json:"owner_user_id,omitempty"`
	Status                 string         `json:"status"`
	IsDefault              bool           `json:"is_default"`
	LatestVersion          int            `json:"latest_version"`
	VersionPublished       bool           `json:"version_published"`
	CreatedAt              time.Time      `json:"created_at"`
	UpdatedAt              time.Time      `json:"updated_at"`
	Tags                   map[string]any `json:"-"`
	Metadata               map[string]any `json:"-"`
	FrontHTML              string         `json:"-"`
	BackHTML               string         `json:"-"`
	CSS                    string         `json:"-"`
	JS                     string         `json:"-"`
	MappingSpec            map[string]any `json:"-"`
	DefaultTemplateID      string         `json:"-"`
	DefaultTemplateVersion int            `json:"-"`
}
