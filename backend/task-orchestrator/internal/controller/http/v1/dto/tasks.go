package dto

type CreateTaskContext struct {
	TemplateID      string `json:"template_id"`
	TemplateVersion int    `json:"template_version,omitempty"`
	TemplateProfile string `json:"template_profile,omitempty"`
}

type ConversationMessage struct {
	Role      string `json:"role"`
	Content   string `json:"content"`
	Timestamp string `json:"timestamp,omitempty"`
	TaskID    string `json:"task_id,omitempty"`
}

type CreateTaskInput struct {
	SessionID           string                `json:"session_id"`
	Query               string                `json:"query,omitempty"`
	ConversationHistory []ConversationMessage `json:"conversation_history,omitempty"`
	Context             CreateTaskContext     `json:"context,omitempty"`
	FileIDs             []string              `json:"file_ids,omitempty"`
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
