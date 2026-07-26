package goagent

import (
	"context"
	"errors"
	"fmt"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentosconversation "github.com/TekkenSteve/GoAgent/agentos/conversation"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"

	"task-orchestrator/internal/usecase"
)

type Conversation struct {
	runtime agentos.ConversationRuntime
}

func NewConversation(runtime agentos.ConversationRuntime) (*Conversation, error) {
	if runtime == nil {
		return nil, fmt.Errorf("goagent conversation runtime is required")
	}
	return &Conversation{runtime: runtime}, nil
}

func (c *Conversation) StartRun(ctx context.Context, request usecase.ConversationStartRequest) (usecase.ConversationRun, error) {
	attachments := make([]agentos.Attachment, 0, len(request.Attachments))
	for _, attachment := range request.Attachments {
		attachments = append(attachments, agentos.Attachment{
			FileID: attachment.FileID, Filename: attachment.Filename, Size: attachment.Size,
			MIMEType: attachment.MIMEType, Metadata: attachment.Metadata,
		})
	}
	var resume *agentos.ConversationResume
	if request.Resume != nil {
		resume = &agentos.ConversationResume{InterruptID: request.Resume.InterruptID, Response: request.Resume.Response}
	}
	run, err := c.runtime.StartRun(ctx, &agentos.StartConversationRunSpec{
		RunID: request.RunID, ThreadID: request.ThreadID, ProcessID: request.ProcessID,
		AccountID: request.AccountID, ProjectID: request.ProjectID, MessageID: request.MessageID,
		UserMessage: request.UserMessage, Attachments: attachments,
		MessageMetadata: request.MessageMetadata, RunMetadata: request.RunMetadata,
		Resume: resume, IdempotencyKey: request.IdempotencyKey, RequestedAt: request.RequestedAt,
	})
	if err != nil {
		return usecase.ConversationRun{}, mapConversationError(err)
	}
	return conversationRun(run), nil
}

func (c *Conversation) IngestEvent(ctx context.Context, event usecase.ExternalConversationEvent) (usecase.ConversationEvent, error) {
	stored, err := c.runtime.IngestEvent(ctx, &agentos.ExternalConversationEvent{
		ThreadID: event.ThreadID, RunID: event.RunID, ProcessID: event.ProcessID,
		AccountID: event.AccountID, ProjectID: event.ProjectID,
		SourceEventID: event.SourceEventID, SourceSequence: event.SourceSequence,
		EventType: agentoscore.EventType(event.EventType), OccurredAt: event.OccurredAt, Payload: event.Payload,
	})
	if err != nil {
		return usecase.ConversationEvent{}, mapConversationError(err)
	}
	return conversationEvent(stored), nil
}

func (c *Conversation) GetThreadSnapshot(ctx context.Context, scope usecase.ConversationThreadScope) (usecase.ConversationThreadSnapshot, error) {
	snapshot, err := c.runtime.GetThreadSnapshot(ctx, agentos.ThreadScope{
		ThreadID: scope.ThreadID, AccountID: scope.AccountID, ProjectID: scope.ProjectID, EventLimit: scope.EventLimit,
	})
	if err != nil {
		return usecase.ConversationThreadSnapshot{}, mapConversationError(err)
	}
	messages := make([]usecase.ConversationMessage, 0, len(snapshot.Messages))
	for _, message := range snapshot.Messages {
		attachments := make([]usecase.ConversationAttachment, 0, len(message.Attachments))
		for _, attachment := range message.Attachments {
			attachments = append(attachments, usecase.ConversationAttachment{
				FileID: attachment.FileID, Filename: attachment.Filename, Size: attachment.Size,
				MIMEType: attachment.MIMEType, Metadata: attachment.Metadata,
			})
		}
		messages = append(messages, usecase.ConversationMessage{
			MessageID: message.MessageID, ThreadID: message.ThreadID, RunID: message.RunID,
			ProcessID: message.ProcessID, Role: message.Role, Content: message.Content,
			Status: message.Status, Attachments: attachments, Metadata: message.Metadata,
			CreatedAt: message.CreatedAt, CompletedAt: message.CompletedAt,
		})
	}
	runs := make([]usecase.ConversationRun, 0, len(snapshot.Runs))
	for _, run := range snapshot.Runs {
		runs = append(runs, conversationRun(run))
	}
	events := make([]usecase.ConversationEvent, 0, len(snapshot.Events))
	for _, event := range snapshot.Events {
		events = append(events, conversationEvent(event))
	}
	return usecase.ConversationThreadSnapshot{
		SchemaVersion: snapshot.SchemaVersion, ThreadID: snapshot.ThreadID,
		Messages: messages, Runs: runs, Events: events, Cursor: snapshot.Cursor, UpdatedAt: snapshot.UpdatedAt,
	}, nil
}

func (c *Conversation) SubscribeThread(ctx context.Context, scope usecase.ConversationStreamScope) (usecase.ConversationSubscription, error) {
	sub, err := c.runtime.SubscribeThread(ctx, agentos.ThreadStreamScope{
		ThreadID: scope.ThreadID, AccountID: scope.AccountID, ProjectID: scope.ProjectID, AfterSequence: scope.AfterSequence,
	})
	if err != nil {
		return nil, mapConversationError(err)
	}
	return newConversationSubscription(ctx, sub), nil
}

type conversationSubscription struct {
	sub    agentoscore.Subscription
	events chan usecase.ConversationEvent
}

func newConversationSubscription(ctx context.Context, sub agentoscore.Subscription) *conversationSubscription {
	result := &conversationSubscription{sub: sub, events: make(chan usecase.ConversationEvent, 64)}
	go func() {
		defer close(result.events)
		for event := range sub.Events() {
			mapped := usecase.ConversationEvent{
				SchemaVersion: usecase.ConversationSchemaVersion, EventID: event.EventID,
				ThreadID: event.ThreadID, RunID: event.RunID, ProcessID: event.ProcessID,
				Sequence: event.Sequence, EventType: string(event.EventType), OccurredAt: event.Timestamp,
				Payload: event.Payload,
			}
			select {
			case result.events <- mapped:
			case <-ctx.Done():
				return
			}
		}
	}()
	return result
}

func (s *conversationSubscription) Events() <-chan usecase.ConversationEvent { return s.events }
func (s *conversationSubscription) Close() error                             { return s.sub.Close() }

func conversationRun(run agentos.ConversationRun) usecase.ConversationRun {
	result := usecase.ConversationRun{
		RunID: run.RunID, ThreadID: run.ThreadID, ProcessID: run.ProcessID, Status: run.Status,
		Outcome: run.Outcome, ErrorCode: run.ErrorCode, Error: run.Error,
		CreatedAt: run.CreatedAt, StartedAt: run.StartedAt, CompletedAt: run.CompletedAt,
	}
	if run.Interrupt != nil {
		result.Interrupt = &usecase.ConversationInterrupt{
			InterruptID: run.Interrupt.InterruptID, Type: run.Interrupt.Type, Prompt: run.Interrupt.Prompt,
			InputSchema: run.Interrupt.InputSchema, Metadata: run.Interrupt.Metadata,
		}
	}
	return result
}

func conversationEvent(event agentos.ConversationEvent) usecase.ConversationEvent {
	return usecase.ConversationEvent{
		SchemaVersion: event.SchemaVersion, EventID: event.EventID, ThreadID: event.ThreadID,
		RunID: event.RunID, ProcessID: event.ProcessID, Sequence: event.Sequence,
		SourceEventID: event.SourceEventID, SourceSequence: event.SourceSequence,
		EventType: string(event.EventType), OccurredAt: event.OccurredAt, Payload: event.Payload,
	}
}

func mapConversationError(err error) error {
	switch {
	case errors.Is(err, agentosconversation.ErrThreadNotFound):
		return fmt.Errorf("%w: %v", usecase.ErrConversationThreadNotFound, err)
	case errors.Is(err, agentosconversation.ErrTenantMismatch):
		return fmt.Errorf("%w: %v", usecase.ErrConversationTenantMismatch, err)
	case errors.Is(err, agentosconversation.ErrInterruptRequired):
		return fmt.Errorf("%w: %v", usecase.ErrConversationInterruptRequired, err)
	case errors.Is(err, agentosconversation.ErrInterruptMismatch):
		return fmt.Errorf("%w: %v", usecase.ErrConversationInterruptMismatch, err)
	default:
		return err
	}
}
