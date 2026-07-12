package usecase

import "time"

type SessionRow struct {
	SessionID        string
	UserID           string
	Title            *string
	Pinned           bool
	TaskCount        int
	TokensUsed       int
	TotalCostUSD     float64
	CreatedAt        time.Time
	UpdatedAt        time.Time
	LastActivityAt   *time.Time
	LatestTaskQuery  *string
	LatestTaskStatus *string
}

type TaskRow struct {
	TaskID      string
	WorkflowID  string
	Query       *string
	Status      *string
	TaskType    *string
	Result      any
	Error       *string
	StartedAt   *time.Time
	CompletedAt *time.Time
	DurationMS  *int64
}

type EventRow struct {
	ID        int64
	TaskID    *string
	Workflow  *string
	Type      string
	Message   *string
	Payload   *string
	StreamID  *string
	Timestamp time.Time
}

type ModelUsageBreakdown struct {
	Model               string
	Provider            string
	Executions          int
	Tokens              int
	CostUSD             float64
	PromptTokens        int
	CompletionTokens    int
	CacheReadTokens     int
	CacheWriteTokens    int
	EstimatedExecutions int
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
	TemplateID             string
	Name                   string
	Description            string
	Scope                  string
	OwnerUserID            string
	Status                 string
	IsDefault              bool
	LatestVersion          int
	VersionPublished       bool
	CreatedAt              time.Time
	UpdatedAt              time.Time
	Tags                   any
	Metadata               map[string]any
	FrontHTML              string
	BackHTML               string
	CSS                    string
	JS                     string
	MappingSpec            map[string]any
	AssetsManifest         map[string]any
	Compatibility          map[string]any
	Changelog              string
	DefaultTemplateID      string
	DefaultTemplateVersion int
}

type TemplateImport struct {
	SourceTemplateID string
	Name             string
	Description      string
	Tags             any
	Metadata         map[string]any
	FrontHTML        string
	BackHTML         string
	CSS              string
	JS               string
	MappingSpec      map[string]any
	AssetsManifest   map[string]any
	Compatibility    map[string]any
	Changelog        string
	Published        bool
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
