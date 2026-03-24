package workflows

import (
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const (
	PauseWorkflowSignal  = "pause-workflow"
	ResumeWorkflowSignal = "resume-workflow"
	CancelWorkflowSignal = "cancel-workflow"
)

type PauseSignal struct {
	Reason    string    `json:"reason"`
	RequestBy string    `json:"request_by"`
	Timestamp time.Time `json:"timestamp"`
}

type ResumeSignal struct {
	Reason    string    `json:"reason"`
	RequestBy string    `json:"request_by"`
	Timestamp time.Time `json:"timestamp"`
}

type CancelSignal struct {
	Reason    string    `json:"reason"`
	RequestBy string    `json:"request_by"`
	Timestamp time.Time `json:"timestamp"`
}

type WorkflowState struct {
	IsPaused     bool      `json:"is_paused"`
	IsCancelled  bool      `json:"is_cancelled"`
	PauseReason  string    `json:"pause_reason,omitempty"`
	PausedBy     string    `json:"paused_by,omitempty"`
	PausedAt     time.Time `json:"paused_at"`
	CancelReason string    `json:"cancel_reason,omitempty"`
	CancelledBy  string    `json:"cancelled_by,omitempty"`
	CancelledAt  time.Time `json:"cancelled_at"`
}

type TaskInput struct {
	TaskID   string         `json:"task_id"`
	UserID   string         `json:"user_id"`
	TaskType string         `json:"task_type"`
	Input    map[string]any `json:"input"`
	Config   map[string]any `json:"config"`
	Metadata map[string]any `json:"metadata"`
}

type TaskOutput struct {
	TaskID      string         `json:"task_id"`
	WorkflowID  string         `json:"workflow_id"`
	RunID       string         `json:"run_id"`
	Status      string         `json:"status"`
	Result      map[string]any `json:"result,omitempty"`
	Error       string         `json:"error,omitempty"`
	StartedAt   time.Time      `json:"started_at"`
	CompletedAt time.Time      `json:"completed_at"`
}

func TaskWorkflow(ctx workflow.Context, input TaskInput) (*TaskOutput, error) {
	logger := workflow.GetLogger(ctx)
	state := WorkflowState{}
	_ = workflow.SetQueryHandler(ctx, "get-workflow-state", func() (WorkflowState, error) { return state, nil })

	pauseSignalChan := workflow.GetSignalChannel(ctx, PauseWorkflowSignal)
	resumeSignalChan := workflow.GetSignalChannel(ctx, ResumeWorkflowSignal)
	cancelSignalChan := workflow.GetSignalChannel(ctx, CancelWorkflowSignal)

	drainSignals := func() {
		for {
			var pause PauseSignal
			if pauseSignalChan.ReceiveAsync(&pause) {
				state.IsPaused = true
				state.PauseReason = pause.Reason
				state.PausedBy = pause.RequestBy
				state.PausedAt = pause.Timestamp
				continue
			}
			var resume ResumeSignal
			if resumeSignalChan.ReceiveAsync(&resume) {
				state.IsPaused = false
				state.PauseReason = ""
				state.PausedBy = ""
				state.PausedAt = time.Time{}
				continue
			}
			var cancel CancelSignal
			if cancelSignalChan.ReceiveAsync(&cancel) {
				state.IsCancelled = true
				state.CancelReason = cancel.Reason
				state.CancelledBy = cancel.RequestBy
				state.CancelledAt = cancel.Timestamp
				continue
			}
			break
		}
	}

	activityQueue := "agent-activities-queue"
	if v, ok := input.Config["activity_task_queue"].(string); ok && v != "" {
		activityQueue = v
	}
	ao := workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Minute,
		TaskQueue:           activityQueue,
		RetryPolicy: &temporal.RetryPolicy{
			MaximumAttempts:    3,
			InitialInterval:    time.Second,
			BackoffCoefficient: 2,
		},
	}
	activityCtx := workflow.WithActivityOptions(ctx, ao)
	persistAO := workflow.ActivityOptions{
		StartToCloseTimeout: 60 * time.Second,
		RetryPolicy: &temporal.RetryPolicy{
			MaximumAttempts:    5,
			InitialInterval:    time.Second,
			BackoffCoefficient: 2,
		},
	}
	persistCtx := workflow.WithActivityOptions(ctx, persistAO)
	payload := map[string]any{
		"task_id":   input.TaskID,
		"user_id":   input.UserID,
		"task_type": input.TaskType,
		"input":     input.Input,
		"config":    input.Config,
		"metadata":  input.Metadata,
	}
	var result map[string]any
	activityFuture := workflow.ExecuteActivity(activityCtx, "execute_agent_workflow", payload)
	activityDone := false
	var activityErr error

	for !activityDone {
		drainSignals()
		if state.IsCancelled {
			return &TaskOutput{
				TaskID:     input.TaskID,
				WorkflowID: workflow.GetInfo(ctx).WorkflowExecution.ID,
				RunID:      workflow.GetInfo(ctx).WorkflowExecution.RunID,
				Status:     "cancelled",
				Error:      "workflow cancelled",
				StartedAt:  workflow.Now(ctx),
			}, temporal.NewCanceledError("workflow cancelled")
		}
		if state.IsPaused {
			selector := workflow.NewSelector(ctx)
			selector.AddReceive(resumeSignalChan, func(c workflow.ReceiveChannel, more bool) {
				var sig ResumeSignal
				c.Receive(ctx, &sig)
				state.IsPaused = false
				state.PauseReason = ""
				state.PausedBy = ""
				state.PausedAt = time.Time{}
			})
			selector.AddReceive(cancelSignalChan, func(c workflow.ReceiveChannel, more bool) {
				var sig CancelSignal
				c.Receive(ctx, &sig)
				state.IsCancelled = true
				state.CancelReason = sig.Reason
				state.CancelledBy = sig.RequestBy
				state.CancelledAt = sig.Timestamp
			})
			selector.AddFuture(activityFuture, func(f workflow.Future) {
				activityDone = true
				activityErr = f.Get(activityCtx, &result)
			})
			selector.Select(ctx)
			continue
		}

		selector := workflow.NewSelector(ctx)
		selector.AddReceive(pauseSignalChan, func(c workflow.ReceiveChannel, more bool) {
			var sig PauseSignal
			c.Receive(ctx, &sig)
			state.IsPaused = true
			state.PauseReason = sig.Reason
			state.PausedBy = sig.RequestBy
			state.PausedAt = sig.Timestamp
		})
		selector.AddReceive(cancelSignalChan, func(c workflow.ReceiveChannel, more bool) {
			var sig CancelSignal
			c.Receive(ctx, &sig)
			state.IsCancelled = true
			state.CancelReason = sig.Reason
			state.CancelledBy = sig.RequestBy
			state.CancelledAt = sig.Timestamp
		})
		selector.AddFuture(activityFuture, func(f workflow.Future) {
			activityDone = true
			activityErr = f.Get(activityCtx, &result)
		})
		selector.Select(ctx)
	}
	if activityErr != nil {
		logger.Error("execute_agent_workflow failed", "task_id", input.TaskID, "err", activityErr)
		failedOutcome := TaskOutcome{
			SchemaVersion: TaskOutcomeSchema,
			TaskID:        input.TaskID,
			WorkflowID:    workflow.GetInfo(ctx).WorkflowExecution.ID,
			Status:        "failed",
			SessionID:     asString(input.Input["session_id"]),
			UserID:        input.UserID,
			Message:       activityErr.Error(),
		}
		_ = workflow.ExecuteActivity(persistCtx, PersistTaskOutcomeActivity, PersistTaskOutcomeInput{
			TaskID:      input.TaskID,
			WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
			Status:      "failed",
			Result:      failedOutcome.ToMap(),
			Error:       activityErr.Error(),
			CompletedAt: workflow.Now(ctx),
		}).Get(persistCtx, nil)
		return &TaskOutput{
			TaskID:      input.TaskID,
			WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
			RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
			Status:      "failed",
			Error:       activityErr.Error(),
			StartedAt:   workflow.Now(ctx),
			CompletedAt: workflow.Now(ctx),
		}, activityErr
	}
	outcome := BuildTaskOutcome(
		input.TaskID,
		workflow.GetInfo(ctx).WorkflowExecution.ID,
		"completed",
		result,
	)
	if outcome.SessionID == "" {
		outcome.SessionID = asString(input.Input["session_id"])
	}
	if outcome.UserID == "" {
		outcome.UserID = input.UserID
	}
	_ = workflow.ExecuteActivity(persistCtx, PersistTaskOutcomeActivity, PersistTaskOutcomeInput{
		TaskID:       input.TaskID,
		WorkflowID:   workflow.GetInfo(ctx).WorkflowExecution.ID,
		Status:       "completed",
		Result:       outcome.ToMap(),
		CompletedAt:  workflow.Now(ctx),
		TerminalNote: outcome.Message,
	}).Get(persistCtx, nil)
	return &TaskOutput{
		TaskID:      input.TaskID,
		WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
		RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
		Status:      "completed",
		Result:      outcome.ToMap(),
		StartedAt:   workflow.Now(ctx),
		CompletedAt: workflow.Now(ctx),
	}, nil
}
