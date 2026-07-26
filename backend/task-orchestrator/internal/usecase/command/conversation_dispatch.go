package command

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"strings"
	"time"

	"github.com/google/uuid"

	"task-orchestrator/internal/usecase"
)

const maxConversationDispatchAttempts = 8

type conversationDispatchPayload struct {
	Start        *usecase.TaskExecutionRequest `json:"start,omitempty"`
	SignalTaskID string                        `json:"signal_task_id,omitempty"`
	Signal       *usecase.TaskExecutionSignal  `json:"signal,omitempty"`
}

func (s *UseCase) enqueueConversationDispatch(ctx context.Context, payload conversationDispatchPayload, item usecase.ConversationDispatch) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode conversation dispatch: %w", err)
	}
	item.DispatchID = uuid.NewString()
	if strings.TrimSpace(item.IdempotencyKey) == "start:" || strings.TrimSpace(item.IdempotencyKey) == "resume:" {
		item.IdempotencyKey += item.RunID
	}
	item.Payload = encoded
	item.CreatedAt = s.now().UTC()
	return s.outbox.EnqueueConversationDispatch(ctx, item)
}

func (s *UseCase) DispatchPendingConversations(ctx context.Context, limit int) error {
	if s.outbox == nil {
		return nil
	}
	items, err := s.outbox.ClaimConversationDispatches(ctx, limit, time.Minute)
	if err != nil {
		return err
	}
	for _, item := range items {
		if err := s.dispatchConversation(ctx, item); err != nil {
			if item.Attempts >= maxConversationDispatchAttempts {
				delivered, deliveryErr := s.conversationDispatchAlreadyDelivered(ctx, item)
				if deliveryErr != nil {
					return deliveryErr
				}
				if delivered {
					if markErr := s.outbox.MarkConversationDispatchDone(ctx, item.DispatchID); markErr != nil {
						return markErr
					}
					continue
				}
				if terminalErr := s.terminalConversationDispatch(ctx, item, err); terminalErr != nil {
					return terminalErr
				}
				if markErr := s.outbox.FailConversationDispatch(ctx, item.DispatchID, err.Error()); markErr != nil {
					return markErr
				}
				continue
			}
			delay := time.Duration(math.Pow(2, float64(item.Attempts-1))) * time.Second
			if delay > time.Minute {
				delay = time.Minute
			}
			if retryErr := s.outbox.RetryConversationDispatch(ctx, item.DispatchID, err.Error(), s.now().UTC().Add(delay)); retryErr != nil {
				return retryErr
			}
			continue
		}
		if err := s.outbox.MarkConversationDispatchDone(ctx, item.DispatchID); err != nil {
			return err
		}
	}
	return nil
}

func (s *UseCase) conversationDispatchAlreadyDelivered(ctx context.Context, item usecase.ConversationDispatch) (bool, error) {
	if s.conversation == nil {
		return false, nil
	}
	snapshot, err := s.conversation.GetThreadSnapshot(ctx, usecase.ConversationThreadScope{
		ThreadID: item.ThreadID, AccountID: item.AccountID, ProjectID: item.ProjectID,
	})
	if err != nil {
		return false, fmt.Errorf("inspect conversation dispatch state: %w", err)
	}
	for _, run := range snapshot.Runs {
		if run.RunID == item.RunID {
			return run.Status != "pending", nil
		}
	}
	return false, fmt.Errorf("inspect conversation dispatch state: run %q not found", item.RunID)
}

func (s *UseCase) dispatchConversation(ctx context.Context, item usecase.ConversationDispatch) error {
	var payload conversationDispatchPayload
	if err := json.Unmarshal(item.Payload, &payload); err != nil {
		return fmt.Errorf("decode conversation dispatch: %w", err)
	}
	switch item.Kind {
	case "start":
		if payload.Start == nil {
			return fmt.Errorf("start dispatch has no request")
		}
		_, err := s.execution.StartTaskExecution(ctx, *payload.Start)
		return err
	case "resume":
		if payload.Signal == nil || strings.TrimSpace(payload.SignalTaskID) == "" {
			return fmt.Errorf("resume dispatch has no signal")
		}
		return s.execution.SignalTaskExecution(ctx, payload.SignalTaskID, *payload.Signal)
	default:
		return fmt.Errorf("unsupported conversation dispatch kind %q", item.Kind)
	}
}

func (s *UseCase) terminalConversationDispatch(ctx context.Context, item usecase.ConversationDispatch, dispatchErr error) error {
	if s.conversation != nil {
		_, err := s.conversation.IngestEvent(ctx, usecase.ExternalConversationEvent{
			ThreadID: item.ThreadID, RunID: item.RunID, ProcessID: item.ProcessID,
			AccountID: item.AccountID, ProjectID: item.ProjectID,
			SourceEventID: "dispatch:" + item.DispatchID + ":failed", SourceSequence: 1,
			EventType: usecase.ConversationEventRunError, OccurredAt: s.now().UTC(),
			Payload: map[string]any{
				"code": "DISPATCH_FAILED", "message": dispatchErr.Error(), "retryable": false,
			},
		})
		if err != nil {
			return fmt.Errorf("persist dispatch terminal event: %w", err)
		}
	}
	if err := s.store.UpdateTaskStatus(ctx, item.ProcessID, "failed", dispatchErr.Error()); err != nil {
		return fmt.Errorf("mark dispatched task failed: %w", err)
	}
	return nil
}

func (s *UseCase) RunConversationDispatcher(ctx context.Context) {
	if s.outbox == nil {
		return
	}
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		if err := s.DispatchPendingConversations(ctx, 25); err != nil && ctx.Err() == nil {
			log.Printf("conversation dispatch retry failed: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
