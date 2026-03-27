package usecase

import (
	"context"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

type WorkflowDescription = dto.WorkflowDescription
type WorkflowState = dto.WorkflowState
type WorkflowHistoryEvent = dto.WorkflowHistoryEvent

type WorkflowService struct {
	runtime port.WorkflowRuntime
	store   port.ReadModelStore
}

func NewWorkflowService(runtime port.WorkflowRuntime, store port.ReadModelStore) *WorkflowService {
	return &WorkflowService{runtime: runtime, store: store}
}

func (s *WorkflowService) Enabled() bool {
	return s != nil && s.runtime != nil && s.runtime.Enabled()
}

func (s *WorkflowService) DescribeWorkflow(ctx context.Context, workflowID, runID string) (*WorkflowDescription, error) {
	if !s.Enabled() {
		return nil, fmt.Errorf("runtime unavailable")
	}
	return s.runtime.DescribeWorkflow(ctx, workflowID, runID)
}

func (s *WorkflowService) GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error) {
	if !s.Enabled() {
		return nil, fmt.Errorf("runtime unavailable")
	}
	return s.runtime.GetWorkflowResult(ctx, workflowID, runID)
}

func (s *WorkflowService) ResolveTaskSession(ctx context.Context, taskID string) (string, error) {
	if s == nil || s.store == nil {
		return "", fmt.Errorf("read model unavailable")
	}
	return s.store.GetTaskSession(ctx, taskID)
}

func (s *WorkflowService) ApplyTaskAction(ctx context.Context, taskID, action, reason, requestBy string) error {
	if !s.Enabled() {
		return fmt.Errorf("runtime unavailable")
	}
	action = strings.ToLower(strings.TrimSpace(action))
	signal := dto.ControlSignal{
		Reason:    reason,
		RequestBy: requestBy,
		Timestamp: time.Now().UTC(),
	}
	var status string
	switch action {
	case "pause":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "pause-workflow", signal); err != nil {
			return err
		}
		status = "paused"
	case "resume":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "resume-workflow", signal); err != nil {
			return err
		}
		status = "running"
	case "cancel":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "cancel-workflow", signal); err != nil {
			return err
		}
		if err := s.runtime.CancelWorkflow(ctx, taskID); err != nil {
			return err
		}
		status = "cancelled"
	default:
		return fmt.Errorf("unsupported action")
	}
	if s.store != nil {
		_ = s.store.UpdateTaskStatus(ctx, taskID, status, "")
	}
	return nil
}

func (s *WorkflowService) QueryControlState(ctx context.Context, taskID string) (*WorkflowState, error) {
	if !s.Enabled() {
		return nil, fmt.Errorf("runtime unavailable")
	}
	return s.runtime.QueryWorkflowState(ctx, taskID)
}

func (s *WorkflowService) CancelWorkflow(ctx context.Context, workflowID, reason string) error {
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

func (s *WorkflowService) ListHistory(ctx context.Context, workflowID string) ([]WorkflowHistoryEvent, error) {
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
	out := make([]WorkflowHistoryEvent, 0, len(events))
	for _, ev := range events {
		out = append(out, WorkflowHistoryEvent{
			EventID:   ev.ID,
			EventType: ev.Type,
			Timestamp: ev.Timestamp,
		})
	}
	return out, nil
}
