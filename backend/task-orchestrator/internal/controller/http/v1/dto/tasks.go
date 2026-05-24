package dto

import "github.com/TekkenSteve/GoAgent/entity"

type CreateTaskContext struct {
	TemplateID      string `json:"template_id"`
	TemplateVersion int    `json:"template_version,omitempty"`
	TemplateProfile string `json:"template_profile,omitempty"`
}

type Attachment struct {
	FileID   string `json:"file_id"`
	Filename string `json:"filename"`
	Size     int64  `json:"size"`
	MimeType string `json:"mime_type"`
}

type CreateTaskInput struct {
	SessionID           string                `json:"session_id"`
	Query               string                `json:"query,omitempty"`
	ConversationHistory []entity.Message `json:"conversation_history,omitempty"`
	Context             CreateTaskContext     `json:"context,omitempty"`
	FilePolicy          string                `json:"file_policy,omitempty"`
	ContextEnvelope     map[string]any        `json:"context_envelope,omitempty"`
	FileIDs             []string              `json:"file_ids,omitempty"`
	EffectiveFileIDs    []string              `json:"effective_file_ids,omitempty"`
	Attachments         []Attachment          `json:"attachments,omitempty"`
	TargetCount         int                   `json:"target_count,omitempty"`
	DifficultyLevel     string                `json:"difficulty_level,omitempty"`
	TemplateID          string                `json:"template_id,omitempty"`
	Variables           map[string]any        `json:"variables,omitempty"`
}

type CreateTaskConfig struct {
	ActivityTaskQueue string `json:"activity_task_queue,omitempty"`
}

type CreateTaskMetadata struct {
	RequestID string `json:"request_id,omitempty"`
	Source    string `json:"source,omitempty"`
	TraceID   string `json:"trace_id,omitempty"`
}

type CreateTaskHTTPBody struct {
	TaskType string             `json:"task_type"`
	UserID   string             `json:"user_id"`
	Query    string             `json:"query"`
	Input    CreateTaskInput    `json:"input"`
	Config   CreateTaskConfig   `json:"config"`
	Metadata CreateTaskMetadata `json:"metadata"`
}
