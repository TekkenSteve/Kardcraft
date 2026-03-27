package dto

import "time"

const (
	TaskTypeMain         = "main"
	TaskTypeCardTemplate = "card_template"
)

type TemplateContext struct {
	TemplateID      string
	TemplateVersion int
	TemplateProfile string
}

type ConversationMessage struct {
	Role      string
	Content   string
	Timestamp string
	TaskID    string
}

type CreateTaskInput struct {
	SessionID           string
	Query               string
	ConversationHistory []ConversationMessage
	Context             TemplateContext
	FileIDs             []string
	TargetCount         int
	DifficultyLevel     string
	TemplateID          string
	Variables           map[string]any
}

type CreateTaskConfig struct {
	ActivityTaskQueue string
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
	Input     CreateTaskInput
	Config    CreateTaskConfig
	Metadata  CreateTaskMetadata
}

type ControlSignal struct {
	Reason    string
	RequestBy string
	Timestamp time.Time
}
