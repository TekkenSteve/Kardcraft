package usecase

import "time"

const (
	TaskTypeMain           = "main"
	TaskTypeCardTemplate   = "card_template"
	AgentSignalUserMessage = "user.message"
)

type CreateTaskResult struct {
	WorkflowID  string
	RunID       string
	ProcessID   string
	Status      string
	SessionID   string
	UserMessage ConversationMessage
	Cursor      int64
}

type SessionControlCommand struct {
	SessionID      string
	TaskID         string
	UserID         string
	Action         string
	Reason         string
	IdempotencyKey string
}

type SessionControlResult struct {
	SessionID           string
	ActiveTaskID        string
	TaskState           string
	SessionControlState string
	Accepted            bool
}

type SessionMessageCommand struct {
	SessionID       string
	UserID          string
	Content         string
	Attachments     []map[string]any
	FileIDs         []string
	Context         map[string]any
	ContextEnvelope map[string]any
	IdempotencyKey  string
	InterruptID     string
	Metadata        map[string]any
	SentAt          time.Time
}

type SessionMessageResult struct {
	SessionID      string              `json:"session_id"`
	ActiveTaskID   string              `json:"active_task_id"`
	RunID          string              `json:"run_id"`
	ProcessID      string              `json:"process_id"`
	UserMessage    ConversationMessage `json:"user_message"`
	Cursor         int64               `json:"cursor"`
	IdempotencyKey string              `json:"idempotency_key"`
	StreamID       string              `json:"stream_id"`
	SentAt         time.Time           `json:"sent_at"`
}

type ConversationDispatch struct {
	DispatchID     string    `json:"dispatch_id"`
	IdempotencyKey string    `json:"idempotency_key"`
	ThreadID       string    `json:"thread_id"`
	RunID          string    `json:"run_id"`
	ProcessID      string    `json:"process_id"`
	AccountID      string    `json:"account_id"`
	ProjectID      string    `json:"project_id"`
	Kind           string    `json:"kind"`
	Payload        []byte    `json:"payload"`
	Attempts       int       `json:"attempts"`
	CreatedAt      time.Time `json:"created_at"`
}

// SessionEvent is an application-level audit record. The command use case
// owns serialization and persistence so HTTP handlers do not write read models.
type SessionEvent struct {
	SessionID  string
	TaskID     string
	WorkflowID string
	Type       string
	Message    string
	Payload    any
	StreamID   string
	OccurredAt time.Time
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
	ConversationHistory []AgentMessage
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

// TaskInputPreparationRequest is the application command for deriving the
// runtime context of a task from its request, session history, and workspace.
// HTTP adapters provide only request values; this use case owns all derived
// execution data and audit records.
type TaskInputPreparationRequest struct {
	TaskID        string
	TaskType      string
	UserID        string
	SessionID     string
	CorrelationID string
	Input         AgentTaskInput
	Attachments   []FileAttachment
}

type FileAttachment struct {
	FileID   string
	Filename string
	Size     int64
	MimeType string
}

type PreparedTaskInput struct {
	Input            AgentTaskInput
	EffectiveFileIDs []string
	SessionEvents    []SessionEvent
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
	TaskID      string
	UserID      string
	TaskType    string
	SessionID   string
	Query       string
	Input       AgentTaskInput
	Attachments []FileAttachment
	Config      CreateTaskConfig
	Metadata    CreateTaskMetadata
}

type ControlSignal struct {
	Reason    string
	RequestBy string
	Timestamp time.Time
}
