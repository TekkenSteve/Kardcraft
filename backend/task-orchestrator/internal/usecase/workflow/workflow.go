package workflow

import (
	"context"
	"fmt"

	"task-orchestrator/internal/usecase"
)

type UseCase struct {
	runtime usecase.WorkflowRuntime
	store   usecase.ReadModelStore
}

func New(runtime usecase.WorkflowRuntime, store usecase.ReadModelStore) *UseCase {
	return &UseCase{runtime: runtime, store: store}
}

func (s *UseCase) Enabled() bool {
	return s != nil && s.runtime != nil && s.runtime.Enabled()
}

func (s *UseCase) DescribeWorkflow(ctx context.Context, workflowID, runID string) (*usecase.WorkflowDescription, error) {
	if !s.Enabled() {
		return nil, fmt.Errorf("runtime unavailable")
	}
	return s.runtime.DescribeWorkflow(ctx, workflowID, runID)
}

func (s *UseCase) GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error) {
	if !s.Enabled() {
		return nil, fmt.Errorf("runtime unavailable")
	}
	return s.runtime.GetWorkflowResult(ctx, workflowID, runID)
}

func (s *UseCase) ResolveTaskSession(ctx context.Context, taskID string) (string, error) {
	if s == nil || s.store == nil {
		return "", fmt.Errorf("read model unavailable")
	}
	return s.store.GetTaskSession(ctx, taskID)
}

func (s *UseCase) QueryControlState(ctx context.Context, taskID string) (*usecase.WorkflowState, error) {
	if s == nil || s.store == nil {
		return nil, fmt.Errorf("read model unavailable")
	}
	events, err := s.store.ListWorkflowEvents(ctx, taskID, 2000, 0)
	if err != nil {
		return nil, err
	}
	state := &usecase.WorkflowState{WorkflowID: taskID, Lifecycle: "running"}
	for _, ev := range events {
		switch ev.Type {
		case usecase.EventWorkflowPaused:
			state.Lifecycle = "paused"
			state.IsPaused = true
			state.PauseReason = stringPtrValue(ev.Message)
			pausedAt := ev.Timestamp
			state.PausedAt = &pausedAt
		case usecase.EventWorkflowResumed:
			state.Lifecycle = "running"
			state.IsPaused = false
			state.PauseReason = ""
			state.PausedAt = nil
		case usecase.EventWorkflowCancelled:
			state.Lifecycle = "cancelled"
			state.IsCancelled = true
			state.CancelReason = stringPtrValue(ev.Message)
			cancelledAt := ev.Timestamp
			state.CancelledAt = &cancelledAt
		}
		state.LastUpdateTime = ev.Timestamp
	}
	return state, nil
}

func (s *UseCase) CancelWorkflow(ctx context.Context, workflowID, reason string) error {
	if !s.Enabled() {
		return fmt.Errorf("runtime unavailable")
	}
	if err := s.runtime.CancelWorkflow(ctx, workflowID); err != nil {
		return err
	}
	if s.store != nil {
		_ = s.store.UpdateTaskStatus(ctx, workflowID, "cancelled", reason)
	}
	return nil
}

func (s *UseCase) ListHistory(ctx context.Context, workflowID string) ([]usecase.WorkflowHistoryEvent, error) {
	if s.Enabled() {
		return s.runtime.ListWorkflowHistory(ctx, workflowID)
	}
	if s == nil || s.store == nil {
		return nil, fmt.Errorf("read model unavailable")
	}
	events, err := s.store.ListWorkflowEvents(ctx, workflowID, 2000, 0)
	if err != nil {
		return nil, err
	}
	out := make([]usecase.WorkflowHistoryEvent, 0, len(events))
	for _, ev := range events {
		out = append(out, usecase.WorkflowHistoryEvent{
			EventID:   ev.ID,
			EventType: ev.Type,
			Timestamp: ev.Timestamp,
		})
	}
	return out, nil
}

func stringPtrValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
