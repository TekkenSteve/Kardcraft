package temporalschedule

import (
	"context"
	"fmt"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	tclient "go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"task-orchestrator/internal/usecase"
)

const DispatchWorkflowName = "KardcraftScheduleDispatchWorkflow"

type DispatchInput struct{ ScheduleID string }

type Runtime struct {
	client tclient.Client
	queue  string
}

func New(client tclient.Client, queue string) *Runtime { return &Runtime{client: client, queue: queue} }

func (r *Runtime) Create(ctx context.Context, row usecase.ScheduleRecord) error {
	_, err := r.client.ScheduleClient().Create(ctx, tclient.ScheduleOptions{
		ID:     row.TemporalScheduleID,
		Spec:   tclient.ScheduleSpec{CronExpressions: []string{row.CronExpression}, TimeZoneName: row.Timezone},
		Action: &tclient.ScheduleWorkflowAction{ID: "dispatch-" + row.ScheduleID, Workflow: DispatchWorkflowName, TaskQueue: r.queue, Args: []interface{}{DispatchInput{ScheduleID: row.ScheduleID}}},
		// Skip is deliberate: overlapping runs duplicate work and model spend.
		Overlap: enumspb.SCHEDULE_OVERLAP_POLICY_SKIP,
		Note:    "Kardcraft skips overlapping schedule runs to avoid duplicate output and model cost.",
	})
	return err
}
func (r *Runtime) Update(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.client.ScheduleClient().GetHandle(ctx, row.TemporalScheduleID).Update(ctx, tclient.ScheduleUpdateOptions{
		DoUpdate: func(_ tclient.ScheduleUpdateInput) (*tclient.ScheduleUpdate, error) {
			return &tclient.ScheduleUpdate{Schedule: &tclient.Schedule{
				Spec: &tclient.ScheduleSpec{
					CronExpressions: []string{row.CronExpression},
					TimeZoneName:    row.Timezone,
				},
				Action: &tclient.ScheduleWorkflowAction{
					ID:        "dispatch-" + row.ScheduleID,
					Workflow:  DispatchWorkflowName,
					TaskQueue: r.queue,
					Args:      []interface{}{DispatchInput{ScheduleID: row.ScheduleID}},
				},
				Policy: &tclient.SchedulePolicies{Overlap: enumspb.SCHEDULE_OVERLAP_POLICY_SKIP},
				State:  &tclient.ScheduleState{Paused: row.Status == "paused"},
			}}, nil
		},
	})
}
func (r *Runtime) Pause(ctx context.Context, row usecase.ScheduleRecord, reason string) error {
	return r.client.ScheduleClient().GetHandle(ctx, row.TemporalScheduleID).Pause(ctx, tclient.SchedulePauseOptions{Note: reason})
}
func (r *Runtime) Resume(ctx context.Context, row usecase.ScheduleRecord, reason string) error {
	return r.client.ScheduleClient().GetHandle(ctx, row.TemporalScheduleID).Unpause(ctx, tclient.ScheduleUnpauseOptions{Note: reason})
}
func (r *Runtime) Delete(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.client.ScheduleClient().GetHandle(ctx, row.TemporalScheduleID).Delete(ctx)
}

func DispatchWorkflow(ctx workflow.Context, input DispatchInput) error {
	activityCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		// Dispatch creates a task. Retrying the activity would create another task
		// for the same schedule tick, so Temporal retries are intentionally disabled.
		RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 1},
	})
	return workflow.ExecuteActivity(activityCtx, "dispatch-scheduled-task", input).Get(ctx, nil)
}

func StartWorker(client tclient.Client, queue string, dispatch func(context.Context, DispatchInput) error) (func(), error) {
	w := worker.New(client, queue, worker.Options{})
	w.RegisterWorkflowWithOptions(DispatchWorkflow, workflow.RegisterOptions{Name: DispatchWorkflowName})
	w.RegisterActivityWithOptions(dispatch, activity.RegisterOptions{Name: "dispatch-scheduled-task"})
	if err := w.Start(); err != nil {
		return nil, fmt.Errorf("start schedule worker: %w", err)
	}
	return w.Stop, nil
}
