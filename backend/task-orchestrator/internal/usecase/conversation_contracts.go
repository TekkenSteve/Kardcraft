package usecase

import (
	"context"
	"errors"
	"time"
)

var (
	ErrConversationThreadNotFound    = errors.New("conversation thread not found")
	ErrConversationTenantMismatch    = errors.New("conversation tenant mismatch")
	ErrConversationInterruptRequired = errors.New("conversation interrupt required")
	ErrConversationInterruptMismatch = errors.New("conversation interrupt mismatch")
)

const ConversationSchemaVersion = "agentos.conversation.v1"

const (
	ConversationEventRunStarted         = "RUN_STARTED"
	ConversationEventTextMessageStart   = "TEXT_MESSAGE_START"
	ConversationEventTextMessageContent = "TEXT_MESSAGE_CONTENT"
	ConversationEventTextMessageEnd     = "TEXT_MESSAGE_END"
	ConversationEventRunFinished        = "RUN_FINISHED"
	ConversationEventRunError           = "RUN_ERROR"
)

type Conversation interface {
	StartRun(context.Context, ConversationStartRequest) (ConversationRun, error)
	IngestEvent(context.Context, ExternalConversationEvent) (ConversationEvent, error)
	GetThreadSnapshot(context.Context, ConversationThreadScope) (ConversationThreadSnapshot, error)
	SubscribeThread(context.Context, ConversationStreamScope) (ConversationSubscription, error)
}

type ConversationAttachment struct {
	FileID   string         `json:"file_id"`
	Filename string         `json:"filename"`
	Size     int64          `json:"size,omitempty"`
	MIMEType string         `json:"mime_type,omitempty"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

type ConversationResume struct {
	InterruptID string `json:"interrupt_id"`
	Response    any    `json:"response"`
}

type ConversationStartRequest struct {
	RunID           string
	ThreadID        string
	ProcessID       string
	AccountID       string
	ProjectID       string
	MessageID       string
	UserMessage     string
	Attachments     []ConversationAttachment
	MessageMetadata map[string]any
	RunMetadata     map[string]any
	Resume          *ConversationResume
	IdempotencyKey  string
	RequestedAt     time.Time
}

type ConversationInterrupt struct {
	InterruptID string         `json:"interrupt_id"`
	Type        string         `json:"type"`
	Prompt      string         `json:"prompt"`
	InputSchema map[string]any `json:"input_schema,omitempty"`
	Metadata    map[string]any `json:"metadata,omitempty"`
}

type ConversationRun struct {
	RunID       string                 `json:"run_id"`
	ThreadID    string                 `json:"thread_id"`
	ProcessID   string                 `json:"process_id,omitempty"`
	Status      string                 `json:"status"`
	Outcome     string                 `json:"outcome,omitempty"`
	Interrupt   *ConversationInterrupt `json:"interrupt,omitempty"`
	ErrorCode   string                 `json:"error_code,omitempty"`
	Error       string                 `json:"error,omitempty"`
	CreatedAt   time.Time              `json:"created_at"`
	StartedAt   time.Time              `json:"started_at,omitempty"`
	CompletedAt time.Time              `json:"completed_at,omitempty"`
}

type ConversationMessage struct {
	MessageID   string                   `json:"message_id"`
	ThreadID    string                   `json:"thread_id"`
	RunID       string                   `json:"run_id"`
	ProcessID   string                   `json:"process_id,omitempty"`
	Role        string                   `json:"role"`
	Content     string                   `json:"content"`
	Status      string                   `json:"status"`
	Attachments []ConversationAttachment `json:"attachments,omitempty"`
	Metadata    map[string]any           `json:"metadata,omitempty"`
	CreatedAt   time.Time                `json:"created_at"`
	CompletedAt time.Time                `json:"completed_at,omitempty"`
}

type ConversationEvent struct {
	SchemaVersion  string         `json:"schema_version"`
	EventID        string         `json:"event_id"`
	ThreadID       string         `json:"thread_id"`
	RunID          string         `json:"run_id"`
	ProcessID      string         `json:"process_id,omitempty"`
	Sequence       int64          `json:"sequence"`
	SourceEventID  string         `json:"source_event_id,omitempty"`
	SourceSequence int64          `json:"source_sequence,omitempty"`
	EventType      string         `json:"event_type"`
	OccurredAt     time.Time      `json:"occurred_at"`
	Payload        map[string]any `json:"payload"`
}

type ExternalConversationEvent struct {
	ThreadID       string
	RunID          string
	ProcessID      string
	AccountID      string
	ProjectID      string
	SourceEventID  string
	SourceSequence int64
	EventType      string
	OccurredAt     time.Time
	Payload        map[string]any
}

type ConversationThreadScope struct {
	ThreadID   string
	AccountID  string
	ProjectID  string
	EventLimit int
}

type ConversationStreamScope struct {
	ThreadID      string
	AccountID     string
	ProjectID     string
	AfterSequence int64
}

type ConversationThreadSnapshot struct {
	SchemaVersion string                `json:"schema_version"`
	ThreadID      string                `json:"thread_id"`
	Messages      []ConversationMessage `json:"messages"`
	Runs          []ConversationRun     `json:"runs"`
	Events        []ConversationEvent   `json:"events"`
	Cursor        int64                 `json:"cursor"`
	UpdatedAt     time.Time             `json:"updated_at"`
}

type ConversationSubscription interface {
	Events() <-chan ConversationEvent
	Close() error
}
