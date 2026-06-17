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

	AgentRuntime interface {
		StartAgentRun(ctx context.Context, req AgentRunRequest) (AgentRunStatus, error)
		SignalAgentRun(ctx context.Context, runID string, signal AgentSignal) error
		ControlAgentRun(ctx context.Context, runID string, op AgentControlOperation) error
		SubscribeAgentEvents(ctx context.Context, scope AgentEventScope) (AgentEventSubscription, error)
	}

	WorkflowRuntime interface {
		Enabled() bool
		DescribeWorkflow(ctx context.Context, workflowID, runID string) (*WorkflowDescription, error)
		GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error)
		CancelWorkflow(ctx context.Context, workflowID string) error
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

type AgentControlOperation string

const (
	AgentControlPause  AgentControlOperation = "pause"
	AgentControlResume AgentControlOperation = "resume"
	AgentControlCancel AgentControlOperation = "cancel"
)

type AgentRunRequest struct {
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
	Backend        AgentBackendRef
	Input          map[string]any
}

type AgentRunStatus struct {
	RunID          string
	LifecycleState string
	Step           int32
	Reason         string
	UpdatedAt      time.Time
}

type AgentBackendRef struct {
	Kind string
	Name string
}

type AgentSignal struct {
	Type           string
	IdempotencyKey string
	Payload        map[string]any
	SentAt         time.Time
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

type AgentEventScope struct {
	RunID         string
	ThreadID      string
	AfterSequence int64
}

type AgentRuntimeEvent struct {
	EventID   string
	EventType string
	RunID     string
	ThreadID  string
	Sequence  int64
	Timestamp time.Time
	Payload   map[string]any
}

type AgentEventSubscription interface {
	Events() <-chan AgentRuntimeEvent
	Close() error
}
