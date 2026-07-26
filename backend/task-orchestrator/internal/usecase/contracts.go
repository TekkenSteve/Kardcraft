// Package usecase declares application use case contracts and shared data shapes.
package usecase

import (
	"context"
	"errors"
	"time"

	"task-orchestrator/internal/entity"
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
		SendMessageToSession(context.Context, SessionMessageCommand) (*SessionMessageResult, error)
		ControlSession(context.Context, SessionControlCommand) (*SessionControlResult, error)
		RecordSessionEvents(context.Context, []SessionEvent) error
	}

	ReadModel interface {
		Ready() bool
		ListSessions(ctx context.Context, userID string, limit, offset int) ([]SessionRow, int, error)
		GetSession(ctx context.Context, sessionID, userID string) (*SessionRow, error)
		GetTask(ctx context.Context, taskID, userID string) (*TaskRow, error)
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
		ImportUserTemplate(ctx context.Context, userID string, input TemplateImport) (TemplateCatalogRow, error)
		InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error
		InsertLLMUsage(ctx context.Context, row UsageLedgerRow) (bool, error)
	}

	CommandSessionStore interface {
		UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error
		InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error)
		ListSessionTasks(ctx context.Context, sessionID, userID string) ([]SessionTask, error)
		UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
		EnsureSessionAccess(ctx context.Context, sessionID, userID string) error
	}

	ConversationDispatchOutbox interface {
		EnqueueConversationDispatch(context.Context, ConversationDispatch) error
		ClaimConversationDispatches(context.Context, int, time.Duration) ([]ConversationDispatch, error)
		MarkConversationDispatchDone(context.Context, string) error
		RetryConversationDispatch(context.Context, string, string, time.Time) error
		FailConversationDispatch(context.Context, string, string) error
	}

	SessionEventRecorder interface {
		InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error
	}

	ReadModelStore interface {
		ReadModel
	}

	TaskExecution interface {
		StartTaskExecution(ctx context.Context, req TaskExecutionRequest) (TaskExecutionStatus, error)
		GetTaskExecutionStatus(ctx context.Context, taskID string) (TaskExecutionStatus, error)
		SignalTaskExecution(ctx context.Context, taskID string, signal TaskExecutionSignal) error
		ControlTaskExecution(ctx context.Context, taskID string, control TaskExecutionControl) error
		SubscribeTaskExecution(ctx context.Context, scope TaskExecutionEventScope) (TaskExecutionSubscription, error)
		IngestTaskExecutionEvent(ctx context.Context, event ExternalTaskExecutionEvent) (TaskExecutionEvent, error)
	}

	ExecutionEventFeed interface {
		Subscribe(ctx context.Context, taskID string, afterSequence int64) (TaskExecutionSubscription, error)
	}

	APKGExport interface {
		CreateAPKGExport(ctx context.Context, command CreateAPKGExportCommand) (APKGExportResult, error)
		GetAPKGExport(ctx context.Context, exportID, sessionID, userID string) (APKGExportResult, error)
		DownloadAPKGExport(ctx context.Context, exportID, sessionID, userID string) (APKGExportDownload, error)
	}

	Workspace interface {
		GetWorkspace(ctx context.Context, sessionID, userID string) (WorkspaceSnapshot, error)
		BulkUpdateCards(ctx context.Context, command BulkCardUpdateCommand) (BulkCardUpdateResult, error)
		DescribeWorkspace(ctx context.Context, sessionID string, now time.Time) (WorkspaceContext, error)
	}

	APKGBuilder interface {
		BuildAPKG(ctx context.Context, request BuildAPKGRequest) (BuildAPKGResult, error)
	}

	TemplateOperations interface {
		ExecuteTemplateOperation(ctx context.Context, command TemplateOperationCommand) (TemplateOperationResult, error)
		PrepareTemplateOperation(ctx context.Context, userID string, command TemplateOperationCommand) (TemplateOperationCommand, error)
		ListTemplates(ctx context.Context, userID string, limit, offset int) (TemplateListResult, error)
		GetTemplate(ctx context.Context, userID, templateID string) (TemplateDetailResult, error)
		ImportTemplate(ctx context.Context, userID string, command TemplateImportCommand) (TemplateImportResult, error)
		GetDefaultTemplate(ctx context.Context, userID string) (TemplateDefaultResult, error)
		SetDefaultTemplate(ctx context.Context, userID string, command SetDefaultTemplateCommand) (TemplateDefaultResult, error)
		ExportTemplate(ctx context.Context, userID, templateID string, exportedAt time.Time) (TemplateExportResult, error)
	}

	TaskInputPreparation interface {
		PrepareTaskInput(ctx context.Context, request TaskInputPreparationRequest) (PreparedTaskInput, error)
	}

	TemplateRuntime interface {
		ExecuteTemplateRuntime(ctx context.Context, operation TemplateOperation, payload map[string]any) (TemplateOperationResult, error)
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

type AgentControlOperation string

const (
	AgentControlPause  AgentControlOperation = "pause"
	AgentControlResume AgentControlOperation = "resume"
	AgentControlCancel AgentControlOperation = "cancel"
)

type TaskExecutionControl struct {
	Operation      AgentControlOperation
	IdempotencyKey string
	RequestedAt    time.Time
	ActorID        string
	Metadata       map[string]string
}

type TaskExecutionRequest struct {
	RunID          string
	ThreadID       string
	AccountID      string
	ProjectID      string
	AgentID        string
	ModelRef       string
	SystemPrompt   string
	UserMessage    string
	IdempotencyKey string
	RequestedAt    time.Time
	Metadata       map[string]string
	Input          map[string]any
}

type TaskExecutionStatus struct {
	TaskID         string
	PlanID         string
	RunID          string
	LifecycleState string
	Progress       *TaskExecutionProgress
	Reason         string
	UpdatedAt      time.Time
}

type TaskExecutionProgress struct {
	Current int32
	Total   int32
	Label   string
}

type TaskExecutionSignal struct {
	Type           string         `json:"type"`
	IdempotencyKey string         `json:"idempotency_key"`
	ActorID        string         `json:"actor_id"`
	Payload        map[string]any `json:"payload"`
	SentAt         time.Time      `json:"sent_at"`
}

type AgentMessage struct {
	Role       string          `json:"role"`
	Content    string          `json:"content,omitempty"`
	ToolCallID string          `json:"tool_call_id,omitempty"`
	ToolCalls  []AgentToolCall `json:"tool_calls,omitempty"`
}

type AgentToolCall struct {
	ID       string                `json:"id"`
	Type     string                `json:"type"`
	Function AgentToolCallFunction `json:"function"`
}

type AgentToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type TaskExecutionEventScope struct {
	TaskID        string
	AfterSequence int64
}

type TaskExecutionEvent struct {
	EventID   string
	EventType string
	RunID     string
	ThreadID  string
	Sequence  int64
	Timestamp time.Time
	Payload   map[string]any
}

// ExternalTaskExecutionEvent is the backend-neutral callback contract used by
// an execution backend to append a durable event to a task's plan stream.
// EventID and Sequence belong to the external source; the execution runtime
// assigns the canonical durable sequence returned in TaskExecutionEvent.
type ExternalTaskExecutionEvent struct {
	EventID   string
	RunID     string
	ThreadID  string
	EventType string
	Source    string
	Sequence  int64
	Timestamp time.Time
	Payload   map[string]any
}

type TaskExecutionSubscription interface {
	Events() <-chan TaskExecutionEvent
	Close() error
}

type CreateAPKGExportCommand struct {
	SessionID  string
	UserID     string
	TemplateID string
	DeckName   string
}

type APKGExportResult struct {
	ExportID       string
	SessionID      string
	TemplateID     string
	DeckName       string
	PackageName    string
	Status         string
	ConfirmedCount int
	FileName       string
	FileSize       int64
	DownloadPath   string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	CompletedAt    *time.Time
	Error          string
}

type APKGExportDownload struct {
	FileName string
	Content  []byte
}

// WorkspaceSnapshot is the HTTP-independent projection of the workspace JSON
// document. Card content remains open because a template owns its fields.
type WorkspaceSnapshot struct {
	SessionID string
	Payload   map[string]any
}

type BulkCardUpdateCommand struct {
	SessionID    string
	UserID       string
	Action       string
	CardIDs      []string
	Status       string
	QuestionType string
}

type BulkCardUpdateResult struct {
	Updated int
}

type WorkspaceContext struct {
	Available      bool
	Status         string
	LifecycleState string
	UpdatedAt      string
	AgeHours       float64
	Version        int64
	CardCount      int
	Cards          []WorkspaceCardSummary
}

type WorkspaceCardSummary struct {
	ID    string
	Title string
	Type  string
}

type BuildAPKGRequest struct {
	DeckName    string
	ModelName   string
	FieldNames  []string
	FrontHTML   string
	BackHTML    string
	CSS         string
	Cards       []APKGCard
	PackageName string
}

type APKGCard struct {
	Fields map[string]string
	Tags   []string
}

type BuildAPKGResult struct {
	FileName string
	Content  []byte
}

type TemplateOperation string

const (
	TemplateOperationPreview        TemplateOperation = "preview"
	TemplateOperationValidate       TemplateOperation = "validate"
	TemplateOperationRequiredFields TemplateOperation = "required_fields"
	TemplateOperationPrecheck       TemplateOperation = "precheck"
	TemplateOperationBuildAPKG      TemplateOperation = "build_apkg"
)

type TemplateOperationCommand struct {
	Operation TemplateOperation
	Payload   map[string]any
}

type TemplateOperationResult struct {
	StatusCode int
	Body       []byte
}

type TemplateSummary struct {
	TemplateID       string
	Name             string
	Description      string
	Scope            string
	OwnerUserID      string
	Status           string
	IsDefault        bool
	LatestVersion    int
	VersionPublished bool
	CreatedAt        time.Time
	UpdatedAt        time.Time
	Tags             any
}

type TemplateListResult struct {
	Templates                  []TemplateSummary
	TotalCount                 int
	UserDefaultTemplateID      string
	UserDefaultTemplateVersion int
}

type TemplateDetailResult struct {
	TemplateSummary
	Tags           any
	Metadata       map[string]any
	FrontHTML      string
	BackHTML       string
	CSS            string
	JS             string
	MappingSpec    map[string]any
	AssetsManifest map[string]any
	Compatibility  map[string]any
	Changelog      string
}

type TemplateImportCommand struct {
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

type TemplateImportResult struct {
	TemplateID string
	Version    int
}

type SetDefaultTemplateCommand struct {
	TemplateID string
	Version    int
}

type TemplateDefaultResult struct {
	UserID     string
	TemplateID string
	Version    int
}

type TemplateExportResult struct {
	Template   TemplateDetailResult
	ExportedAt time.Time
}
