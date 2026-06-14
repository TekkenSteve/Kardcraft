package usecase

import (
	"time"

	goagententity "github.com/TekkenSteve/GoAgent/entity"
)

const TaskWorkflowName = "TaskWorkflow"

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
