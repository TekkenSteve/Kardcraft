// Package usecase declares application use case contracts and shared data shapes.
package usecase

import (
	"context"
	"errors"
	"time"

	goagententity "github.com/TekkenSteve/GoAgent/entity"

	"task-orchestrator/internal/entity"
)

const (
	TaskTypeMain         = "main"
	TaskTypeCardTemplate = "card_template"
	TaskWorkflowName     = "TaskWorkflow"
)

type (
	Task interface {
		CreateTask(context.Context, CreateTaskInput) (*entity.Task, error)
		StartTask(context.Context, string) error
		CompleteTask(context.Context, string) error
		FailTask(context.Context, string, string) error
		PauseTask(context.Context, string, string) error
		ResumeTask(context.Context, string, string) error
		CancelTask(context.Context, string, string) error
		GetTask(context.Context, string) (*entity.Task, error)
		ListTasks(context.Context, ListTasksInput) ([]*entity.Task, int, error)
	}

	Command interface {
		CreateTaskInSession(context.Context, CreateTaskCommand) (*CreateTaskResult, string, error)
		ControlSession(context.Context, SessionControlCommand) (*SessionControlResult, error)
	}

	ReadModel interface {
		Ready() bool
		ListSessions(ctx context.Context, userID string, limit, offset int) ([]SessionRow, int, error)
		GetSession(ctx context.Context, sessionID, userID string) (*SessionRow, error)
		UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error
		DeleteSession(ctx context.Context, sessionID, userID string) (int64, error)
		ListSessionTasks(ctx context.Context, sessionID, userID string) ([]TaskRow, error)
		ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]EventRow, error)
		ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]EventRow, error)
		LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error)
		SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error
		MarkSessionActive(ctx context.Context, sessionID, userID string) error
		GetTaskSession(ctx context.Context, taskID string) (string, error)
		UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
		GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]TaskUsageSummary, error)
		GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]TaskUsageSummary, error)
		ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]TemplateCatalogRow, int, error)
		GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*TemplateCatalogRow, error)
		GetUserTemplatePreference(ctx context.Context, userID string) (*TemplateCatalogRow, error)
		GetResolvedDefaultTemplate(ctx context.Context, userID string) (*TemplateCatalogRow, error)
		UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error
		InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error
		InsertLLMUsage(ctx context.Context, row UsageLedgerRow) (bool, error)
	}

	Workflow interface {
		Enabled() bool
		DescribeWorkflow(ctx context.Context, workflowID, runID string) (*WorkflowDescription, error)
		GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error)
		ResolveTaskSession(ctx context.Context, taskID string) (string, error)
		QueryControlState(ctx context.Context, taskID string) (*WorkflowState, error)
		CancelWorkflow(ctx context.Context, workflowID, reason string) error
		ListHistory(ctx context.Context, workflowID string) ([]WorkflowHistoryEvent, error)
	}

	CommandSessionStore interface {
		UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error
		InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error)
		ListSessionTasks(ctx context.Context, sessionID, userID string) ([]SessionTask, error)
		UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
		EnsureSessionAccess(ctx context.Context, sessionID, userID string) error
	}

	ReadModelStore interface {
		ReadModel
	}

	AgentExecutor interface {
		Execute(ctx context.Context, req *goagententity.ExecuteRequest) (goagententity.RunStatus, error)
		Control(ctx context.Context, runID string, op goagententity.ControlOperation) error
	}

	CommandRuntime interface {
		StartTaskWorkflow(ctx context.Context, cmd CreateTaskCommand) (string, error)
		SignalWorkflow(ctx context.Context, taskID, signalName string, signal ControlSignal) error
		CancelWorkflow(ctx context.Context, taskID string) error
	}

	WorkflowRuntime interface {
		Enabled() bool
		DescribeWorkflow(ctx context.Context, workflowID, runID string) (*WorkflowDescription, error)
		GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error)
		SignalWorkflow(ctx context.Context, workflowID, signalName string, signal ControlSignal) error
		CancelWorkflow(ctx context.Context, workflowID string) error
		QueryWorkflowState(ctx context.Context, workflowID string) (*WorkflowState, error)
		ListWorkflowHistory(ctx context.Context, workflowID string) ([]WorkflowHistoryEvent, error)
	}
)

var (
	ErrTaskNotFound      = errors.New("task not found")
	ErrActiveTaskExists  = errors.New("session already has an active task")
	ErrNoActiveTask      = errors.New("session has no active task")
	ErrInvalidTransition = errors.New("invalid task state transition")
)

type Clock func() time.Time

type CreateTaskInput struct {
	TaskID    string
	TaskType  string
	UserID    string
	Query     string
	SessionID string
}

type ListTasksInput struct {
	UserID string
	Limit  int
	Offset int
}

type CreateTaskResult struct {
	WorkflowID string
	RunID      string
	Status     string
	SessionID  string
}

type SessionControlCommand struct {
	SessionID string
	TaskID    string
	UserID    string
	Action    string
	Reason    string
}

type SessionControlResult struct {
	SessionID           string
	ActiveTaskID        string
	TaskState           string
	SessionControlState string
	Accepted            bool
}

type SessionTask struct {
	TaskID   string
	Status   string
	TaskType string
}

type TemplateContext struct {
	TemplateID      string
	TemplateVersion int
	TemplateProfile string
}

type AgentTaskInput struct {
	SessionID           string
	Query               string
	ConversationHistory []goagententity.Message
	Context             TemplateContext
	FilePolicy          string
	ContextEnvelope     map[string]any
	FileIDs             []string
	EffectiveFileIDs    []string
	TargetCount         int
	DifficultyLevel     string
	TemplateID          string
	Variables           map[string]any
}

type CreateTaskConfig struct {
	ActivityTaskQueue string
	ModelRef          string
}

type CreateTaskMetadata struct {
	RequestID string
	Source    string
	TraceID   string
}

type CreateTaskCommand struct {
	TaskID    string
	UserID    string
	TaskType  string
	SessionID string
	Query     string
	Input     AgentTaskInput
	Config    CreateTaskConfig
	Metadata  CreateTaskMetadata
}

type WorkflowTaskType string

const (
	WorkflowTaskTypeMain         WorkflowTaskType = TaskTypeMain
	WorkflowTaskTypeCardTemplate WorkflowTaskType = TaskTypeCardTemplate
)

type WorkflowTaskInputContext struct {
	TemplateID      string `json:"template_id"`
	TemplateVersion int    `json:"template_version,omitempty"`
	TemplateProfile string `json:"template_profile,omitempty"`
}

type WorkflowTaskInputPayload struct {
	SessionID           string                   `json:"session_id"`
	Query               string                   `json:"query,omitempty"`
	ConversationHistory []goagententity.Message  `json:"conversation_history,omitempty"`
	Context             WorkflowTaskInputContext `json:"context,omitempty"`
	FilePolicy          string                   `json:"file_policy,omitempty"`
	ContextEnvelope     map[string]any           `json:"context_envelope,omitempty"`
	FileIDs             []string                 `json:"file_ids,omitempty"`
	EffectiveFileIDs    []string                 `json:"effective_file_ids,omitempty"`
	TargetCount         int                      `json:"target_count,omitempty"`
	DifficultyLevel     string                   `json:"difficulty_level,omitempty"`
	TemplateID          string                   `json:"template_id,omitempty"`
	Variables           map[string]any           `json:"variables,omitempty"`
}

type WorkflowTaskConfig struct {
	ActivityTaskQueue string `json:"activity_task_queue,omitempty"`
}

type WorkflowTaskMetadata struct {
	RequestID string `json:"request_id,omitempty"`
	Source    string `json:"source,omitempty"`
	TraceID   string `json:"trace_id,omitempty"`
}

type WorkflowTaskInput struct {
	TaskID   string                   `json:"task_id"`
	UserID   string                   `json:"user_id"`
	TaskType WorkflowTaskType         `json:"task_type"`
	Input    WorkflowTaskInputPayload `json:"input"`
	Config   WorkflowTaskConfig       `json:"config"`
	Metadata WorkflowTaskMetadata     `json:"metadata"`
}

type WorkflowTaskOutput struct {
	TaskID      string         `json:"task_id"`
	WorkflowID  string         `json:"workflow_id"`
	RunID       string         `json:"run_id"`
	Status      string         `json:"status"`
	Result      map[string]any `json:"result,omitempty"`
	Error       string         `json:"error,omitempty"`
	StartedAt   time.Time      `json:"started_at"`
	CompletedAt time.Time      `json:"completed_at"`
}

type ControlSignal struct {
	Reason    string
	RequestBy string
	Timestamp time.Time
}

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
	Tags                   map[string]any
	Metadata               map[string]any
	FrontHTML              string
	BackHTML               string
	CSS                    string
	JS                     string
	MappingSpec            map[string]any
	DefaultTemplateID      string
	DefaultTemplateVersion int
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

type WorkflowDescription struct {
	WorkflowID string
	RunID      string
	Status     string
	StartTime  time.Time
	CloseTime  *time.Time
}

type WorkflowState struct {
	IsPaused     bool
	IsCancelled  bool
	PausedAt     *time.Time
	PauseReason  string
	CancelReason string
}

type WorkflowHistoryEvent struct {
	EventID   int64
	EventType string
	Timestamp time.Time
}
