package temporal

import (
	"fmt"
	"strings"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"task-orchestrator/internal/usecase"
	outcomemodel "task-orchestrator/internal/usecase/outcome"
)

// CommandSignal is the unified signal payload received on the AgentCommandSignal channel.
// Command must be one of "pause", "resume", or "cancel".
type CommandSignal struct {
	Command   string    `json:"command"`
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

type TaskType = usecase.WorkflowTaskType

const (
	TaskTypeMain         = usecase.WorkflowTaskTypeMain
	TaskTypeCardTemplate = usecase.WorkflowTaskTypeCardTemplate
)

type TaskInputContext = usecase.WorkflowTaskInputContext
type TaskInputPayload = usecase.WorkflowTaskInputPayload
type TaskConfig = usecase.WorkflowTaskConfig
type TaskMetadata = usecase.WorkflowTaskMetadata
type TaskInput = usecase.WorkflowTaskInput

type TaskOutput = usecase.WorkflowTaskOutput

func TaskWorkflow(ctx workflow.Context, input TaskInput) (*TaskOutput, error) {
	logger := workflow.GetLogger(ctx)
	state := WorkflowState{}
	_ = workflow.SetQueryHandler(ctx, QueryRunStatus, func() (RunStatus, error) {
		return workflowStateToRunStatus(state, workflow.GetInfo(ctx).WorkflowExecution.RunID), nil
	})

	commandSignalChan := workflow.GetSignalChannel(ctx, CommandSignalName)

	activityQueue := "agent-activities-queue"
	if strings.TrimSpace(input.Config.ActivityTaskQueue) != "" {
		activityQueue = strings.TrimSpace(input.Config.ActivityTaskQueue)
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

	if err := validateTaskActivityPayload(input); err != nil {
		logger.Error("invalid task input before execute_agent_workflow", "task_id", input.TaskID, "err", err)
		return &TaskOutput{
			TaskID:      input.TaskID,
			WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
			RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
			Status:      "failed",
			Error:       err.Error(),
			StartedAt:   workflow.Now(ctx),
			CompletedAt: workflow.Now(ctx),
		}, temporal.NewNonRetryableApplicationError(err.Error(), "InvalidTaskInput", nil)
	}

	// Cross-language contract boundary:
	// Top-level payload only carries task envelope fields. Business fields stay inside `input`.
	payload := map[string]any{
		"task_id":   input.TaskID,
		"user_id":   input.UserID,
		"task_type": string(input.TaskType),
		"input":     input.Input,
		"config":    input.Config,
		"metadata":  input.Metadata,
	}
	var result map[string]any
	var activityFuture workflow.Future
	var cancelActivity workflow.CancelFunc
	activityDone := false
	var activityErr error
	resumeRequested := false
	startActivity := func(activityName string, activityPayload map[string]any) {
		var cancellableActivityCtx workflow.Context
		cancellableActivityCtx, cancelActivity = workflow.WithCancel(activityCtx)
		activityFuture = workflow.ExecuteActivity(cancellableActivityCtx, activityName, activityPayload)
		activityDone = false
		activityErr = nil
	}
	startResumeActivity := func() {
		additionalInput := map[string]any{
			"task_id":              input.TaskID,
			"user_id":              input.UserID,
			"session_id":           strings.TrimSpace(input.Input.SessionID),
			"task_type":            string(input.TaskType),
			"input":                input.Input,
			"workspace_id":         strings.TrimSpace(input.Input.SessionID),
			"user_input":           input.Input.Query,
			"conversation_history": input.Input.ConversationHistory,
			"file_ids":             input.Input.FileIDs,
			"target_count":         input.Input.TargetCount,
			"difficulty_level":     input.Input.DifficultyLevel,
			"metadata":             input.Metadata,
			"config":               input.Config,
		}
		startActivity("resume_agent_workflow", map[string]any{
			"task_id":          input.TaskID,
			"checkpoint_id":    input.TaskID,
			"session_id":       strings.TrimSpace(input.Input.SessionID),
			"user_id":          input.UserID,
			"metadata":         input.Metadata,
			"additional_input": additionalInput,
		})
	}
	applyQueuedResume := func() bool {
		consumeResume, startResume := decideResumeAfterPause(resumeRequested, activityDone, activityErr)
		if !consumeResume {
			return false
		}
		resumeRequested = false
		state.IsPaused = false
		if startResume {
			startResumeActivity()
			return true
		}
		return false
	}

	// drainSignals reads all queued command signals from the unified channel.
	drainSignals := func() {
		for {
			var cmd CommandSignal
			if !commandSignalChan.ReceiveAsync(&cmd) {
				break
			}
			switch cmd.Command {
			case CommandPause:
				state.IsPaused = true
				state.PauseReason = cmd.Reason
				state.PausedBy = cmd.RequestBy
				state.PausedAt = cmd.Timestamp
				if cancelActivity != nil && !activityDone {
					cancelActivity()
				}
			case CommandResume:
				state.PauseReason = ""
				state.PausedBy = ""
				state.PausedAt = time.Time{}
				if state.IsPaused {
					resumeRequested = true
				} else {
					state.IsPaused = false
				}
			case CommandCancel:
				state.IsCancelled = true
				state.CancelReason = cmd.Reason
				state.CancelledBy = cmd.RequestBy
				state.CancelledAt = cmd.Timestamp
			}
		}
	}
	startActivity("execute_agent_workflow", payload)

	for {
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
		if activityDone && !state.IsPaused {
			break
		}
		if state.IsPaused {
			if applyQueuedResume() {
				continue
			}
			selector := workflow.NewSelector(ctx)
			selector.AddReceive(commandSignalChan, func(c workflow.ReceiveChannel, more bool) {
				var cmd CommandSignal
				c.Receive(ctx, &cmd)
				switch cmd.Command {
				case CommandResume:
					state.PauseReason = ""
					state.PausedBy = ""
					state.PausedAt = time.Time{}
					resumeRequested = true
				case CommandCancel:
					state.IsCancelled = true
					state.CancelReason = cmd.Reason
					state.CancelledBy = cmd.RequestBy
					state.CancelledAt = cmd.Timestamp
				}
			})
			if activityFuture != nil && !activityDone {
				selector.AddFuture(activityFuture, func(f workflow.Future) {
					activityDone = true
					activityErr = f.Get(activityCtx, &result)
				})
			}
			selector.Select(ctx)
			if applyQueuedResume() {
				continue
			}
			continue
		}

		selector := workflow.NewSelector(ctx)
		selector.AddReceive(commandSignalChan, func(c workflow.ReceiveChannel, more bool) {
			var cmd CommandSignal
			c.Receive(ctx, &cmd)
			switch cmd.Command {
			case CommandPause:
				state.IsPaused = true
				state.PauseReason = cmd.Reason
				state.PausedBy = cmd.RequestBy
				state.PausedAt = cmd.Timestamp
				if cancelActivity != nil && !activityDone {
					cancelActivity()
				}
			case CommandCancel:
				state.IsCancelled = true
				state.CancelReason = cmd.Reason
				state.CancelledBy = cmd.RequestBy
				state.CancelledAt = cmd.Timestamp
			}
		})
		selector.AddFuture(activityFuture, func(f workflow.Future) {
			activityDone = true
			activityErr = f.Get(activityCtx, &result)
		})
		selector.Select(ctx)
	}
	if activityErr != nil {
		logger.Error("execute_agent_workflow failed", "task_id", input.TaskID, "err", activityErr)
		failedOutcome := outcomemodel.TaskOutcome{
			SchemaVersion: outcomemodel.TaskOutcomeSchema,
			TaskID:        input.TaskID,
			WorkflowID:    workflow.GetInfo(ctx).WorkflowExecution.ID,
			Status:        "failed",
			SessionID:     strings.TrimSpace(input.Input.SessionID),
			UserID:        input.UserID,
			Message:       activityErr.Error(),
		}
		persistErr := workflow.ExecuteActivity(persistCtx, PersistTaskOutcomeActivity, PersistTaskOutcomeInput{
			TaskID:        input.TaskID,
			WorkflowID:    workflow.GetInfo(ctx).WorkflowExecution.ID,
			RunID:         workflow.GetInfo(ctx).WorkflowExecution.RunID,
			CorrelationID: resolveTaskCorrelationID(input),
			Status:        "failed",
			Result:        failedOutcome.ToMap(),
			Error:         activityErr.Error(),
			CompletedAt:   workflow.Now(ctx),
		}).Get(persistCtx, nil)
		if persistErr != nil {
			logger.Error("persist failed outcome failed", "task_id", input.TaskID, "err", persistErr)
			return &TaskOutput{
				TaskID:      input.TaskID,
				WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
				RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
				Status:      "failed",
				Error:       persistErr.Error(),
				StartedAt:   workflow.Now(ctx),
				CompletedAt: workflow.Now(ctx),
			}, persistErr
		}
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
	outcome := outcomemodel.BuildTaskOutcome(
		input.TaskID,
		workflow.GetInfo(ctx).WorkflowExecution.ID,
		"completed",
		result,
	)
	if outcome.SessionID == "" {
		outcome.SessionID = strings.TrimSpace(input.Input.SessionID)
	}
	if outcome.UserID == "" {
		outcome.UserID = input.UserID
	}
	if err := workflow.ExecuteActivity(persistCtx, PersistTaskOutcomeActivity, PersistTaskOutcomeInput{
		TaskID:        input.TaskID,
		WorkflowID:    workflow.GetInfo(ctx).WorkflowExecution.ID,
		RunID:         workflow.GetInfo(ctx).WorkflowExecution.RunID,
		CorrelationID: resolveTaskCorrelationID(input),
		Status:        outcome.Status,
		Result:        outcome.ToMap(),
		CompletedAt:   workflow.Now(ctx),
		TerminalNote:  outcome.Message,
	}).Get(persistCtx, nil); err != nil {
		logger.Error("persist completed outcome failed", "task_id", input.TaskID, "err", err)
		return &TaskOutput{
			TaskID:      input.TaskID,
			WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
			RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
			Status:      "failed",
			Error:       err.Error(),
			StartedAt:   workflow.Now(ctx),
			CompletedAt: workflow.Now(ctx),
		}, err
	}
	return &TaskOutput{
		TaskID:      input.TaskID,
		WorkflowID:  workflow.GetInfo(ctx).WorkflowExecution.ID,
		RunID:       workflow.GetInfo(ctx).WorkflowExecution.RunID,
		Status:      outcome.Status,
		Result:      outcome.ToMap(),
		StartedAt:   workflow.Now(ctx),
		CompletedAt: workflow.Now(ctx),
	}, nil
}

func resolveTaskCorrelationID(input TaskInput) string {
	correlationID := strings.TrimSpace(input.Metadata.RequestID)
	if correlationID != "" {
		return correlationID
	}
	if input.Input.ContextEnvelope != nil {
		if value, ok := input.Input.ContextEnvelope["correlation_id"].(string); ok {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func decideResumeAfterPause(resumeRequested bool, activityDone bool, activityErr error) (consumeResume bool, startResumeActivity bool) {
	if !resumeRequested {
		return false, false
	}
	if !activityDone {
		return true, true
	}
	return true, temporal.IsCanceledError(activityErr)
}

func validateTaskActivityPayload(input TaskInput) error {
	sessionID := strings.TrimSpace(input.Input.SessionID)
	if sessionID == "" {
		return fmt.Errorf("input.session_id is required")
	}

	switch input.TaskType {
	case TaskTypeMain:
		query := strings.TrimSpace(input.Input.Query)
		if query == "" {
			return fmt.Errorf("input.query is required for main task")
		}
		templateID := strings.TrimSpace(input.Input.Context.TemplateID)
		if templateID == "" {
			return fmt.Errorf("input.context.template_id is required for main task")
		}
	case TaskTypeCardTemplate:
		templateID := strings.TrimSpace(input.Input.TemplateID)
		if templateID == "" {
			return fmt.Errorf("input.template_id is required for card_template task")
		}
	default:
		return fmt.Errorf("unsupported task_type: %s", strings.TrimSpace(string(input.TaskType)))
	}

	return nil
}

func workflowStateToRunStatus(state WorkflowState, runID string) RunStatus {
	lifecycle := "running"
	reason := ""
	var updatedAt time.Time
	switch {
	case state.IsCancelled:
		lifecycle = LifecycleStateCanceled
		reason = state.CancelReason
		updatedAt = state.CancelledAt
	case state.IsPaused:
		lifecycle = "paused"
		reason = state.PauseReason
		updatedAt = state.PausedAt
	}
	return RunStatus{
		RunID:          runID,
		LifecycleState: lifecycle,
		Reason:         reason,
		UpdatedAt:      updatedAt,
	}
}
