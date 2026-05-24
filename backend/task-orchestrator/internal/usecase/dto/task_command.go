package dto

import (
	"time"

	"github.com/TekkenSteve/GoAgent/entity"
)

const (
	TaskTypeMain         = "main"
	TaskTypeCardTemplate = "card_template"
)

type TemplateContext struct {
	TemplateID      string
	TemplateVersion int
	TemplateProfile string
}

type CreateTaskInput struct {
	SessionID           string
	Query               string
	ConversationHistory []entity.Message
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
