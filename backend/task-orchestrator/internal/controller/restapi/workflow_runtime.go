package restapi

import (
	"context"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	tclient "go.temporal.io/sdk/client"

	"task-orchestrator/internal/usecase"
)

type temporalWorkflowRuntime struct {
	client tclient.Client
}

func NewTemporalWorkflowRuntime(client tclient.Client) usecase.WorkflowRuntime {
	return temporalWorkflowRuntime{client: client}
}

func (r temporalWorkflowRuntime) Enabled() bool {
	return r.client != nil
}

func (r temporalWorkflowRuntime) DescribeWorkflow(ctx context.Context, workflowID, runID string) (*usecase.WorkflowDescription, error) {
	resp, err := r.client.DescribeWorkflowExecution(ctx, workflowID, runID)
	if err != nil {
		return nil, err
	}
	var closeTime *time.Time
	if resp.WorkflowExecutionInfo.CloseTime != nil {
		t := resp.WorkflowExecutionInfo.CloseTime.AsTime().UTC()
		closeTime = &t
	}
	return &usecase.WorkflowDescription{
		WorkflowID: workflowID,
		RunID:      resp.WorkflowExecutionInfo.Execution.RunId,
		Status:     mapRuntimeStatus(resp.WorkflowExecutionInfo.Status),
		StartTime:  resp.WorkflowExecutionInfo.StartTime.AsTime().UTC(),
		CloseTime:  closeTime,
	}, nil
}

func (r temporalWorkflowRuntime) GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error) {
	wr := r.client.GetWorkflow(ctx, workflowID, runID)
	var result any
	if err := wr.Get(ctx, &result); err != nil {
		return nil, err
	}
	return result, nil
}

func (r temporalWorkflowRuntime) CancelWorkflow(ctx context.Context, workflowID string) error {
	return r.client.CancelWorkflow(ctx, workflowID, "")
}

func (r temporalWorkflowRuntime) ListWorkflowHistory(ctx context.Context, workflowID string) ([]usecase.WorkflowHistoryEvent, error) {
	iter := r.client.GetWorkflowHistory(ctx, workflowID, "", false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	out := make([]usecase.WorkflowHistoryEvent, 0)
	for iter.HasNext() {
		ev, err := iter.Next()
		if err != nil {
			return out, err
		}
		out = append(out, usecase.WorkflowHistoryEvent{
			EventID:   ev.EventId,
			EventType: ev.EventType.String(),
			Timestamp: ev.EventTime.AsTime().UTC(),
		})
	}
	return out, nil
}

func mapRuntimeStatus(st enumspb.WorkflowExecutionStatus) string {
	switch st {
	case enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING:
		return "TASK_STATUS_RUNNING"
	case enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED:
		return "TASK_STATUS_COMPLETED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_FAILED:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_CANCELED:
		return "TASK_STATUS_CANCELLED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_TERMINATED:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_CONTINUED_AS_NEW:
		return "TASK_STATUS_RUNNING"
	default:
		return "TASK_STATUS_QUEUED"
	}
}
