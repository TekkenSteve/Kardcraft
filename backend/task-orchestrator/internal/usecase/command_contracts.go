package usecase

import "time"

const (
	TaskTypeMain           = "main"
	TaskTypeCardTemplate   = "card_template"
	AgentSignalUserMessage = "user.message"
)

type CreateTaskResult struct {
	WorkflowID string
	RunID      string
	Status     string
	SessionID  string
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
	Metadata        map[string]any
	SentAt          time.Time
}

type SessionMessageResult struct {
	SessionID      string
	ActiveTaskID   string
	IdempotencyKey string
	SentAt         time.Time
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

type ControlSignal struct {
	Reason    string
	RequestBy string
	Timestamp time.Time
}
