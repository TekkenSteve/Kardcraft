package port

import (
	"context"

	"task-orchestrator/internal/usecase/dto"
)

type CommandRuntime interface {
	StartTaskWorkflow(ctx context.Context, cmd dto.CreateTaskCommand) (string, error)
	SignalWorkflow(ctx context.Context, taskID, signalName string, signal dto.ControlSignal) error
	CancelWorkflow(ctx context.Context, taskID string) error
}

type WorkflowRuntime interface {
	Enabled() bool
	DescribeWorkflow(ctx context.Context, workflowID, runID string) (*dto.WorkflowDescription, error)
	GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error)
	SignalWorkflow(ctx context.Context, workflowID, signalName string, signal dto.ControlSignal) error
	CancelWorkflow(ctx context.Context, workflowID string) error
	QueryWorkflowState(ctx context.Context, workflowID string) (*dto.WorkflowState, error)
	ListWorkflowHistory(ctx context.Context, workflowID string) ([]dto.WorkflowHistoryEvent, error)
}
