package usecase

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

var (
	ErrActiveTaskExists  = errors.New("session already has an active task")
	ErrNoActiveTask      = errors.New("session has no active task")
	ErrInvalidTransition = errors.New("invalid task state transition")
)

type CreateTaskResult struct {
	WorkflowID string
	RunID      string
	Status     string
	SessionID  string
}

type SessionControlCommand struct {
	SessionID string
	UserID    string
	Action    string
	Reason    string
}

type SessionControlResult struct {
	SessionID           string
	ActiveTaskID        string
	TaskState           string
	SessionControlState string
	Accepted            bool
}

type CommandService struct {
	tasks   *TaskService
	store   port.CommandSessionStore
	runtime port.CommandRuntime
	now     func() time.Time
}

func NewCommandService(tasks *TaskService, store port.CommandSessionStore, runtime port.CommandRuntime) *CommandService {
	return &CommandService{tasks: tasks, store: store, runtime: runtime, now: time.Now}
}

func (s *CommandService) CreateTaskInSession(ctx context.Context, cmd dto.CreateTaskCommand) (*CreateTaskResult, string, error) {
	if err := s.store.UpsertSession(ctx, cmd.SessionID, cmd.UserID, cmd.Query, "pending"); err != nil {
		return nil, "", err
	}
	inserted, err := s.store.InsertTaskIfNoActive(ctx, cmd.TaskID, cmd.SessionID, cmd.UserID, cmd.TaskType, "pending", cmd.Query)
	if err != nil {
		return nil, "", err
	}
	if !inserted {
		tasks, listErr := s.store.ListSessionTasks(ctx, cmd.SessionID, cmd.UserID)
		activeTaskID := ""
		if listErr == nil {
			if taskID, ok := resolveActiveTaskID(tasks); ok {
				activeTaskID = taskID
			}
		}
		return nil, activeTaskID, ErrActiveTaskExists
	}

	_, err = s.tasks.CreateTask(ctx, CreateTaskInput{
		TaskID:    cmd.TaskID,
		TaskType:  cmd.TaskType,
		UserID:    cmd.UserID,
		Query:     cmd.Query,
		SessionID: cmd.SessionID,
	})
	if err != nil {
		_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
		return nil, "", err
	}

	runID, err := s.runtime.StartTaskWorkflow(ctx, cmd)
	if err != nil {
		_ = s.store.UpdateTaskStatus(ctx, cmd.TaskID, "failed", err.Error())
		return nil, "", err
	}

	return &CreateTaskResult{
		WorkflowID: cmd.TaskID,
		RunID:      runID,
		Status:     "pending",
		SessionID:  cmd.SessionID,
	}, "", nil
}

func (s *CommandService) ControlSession(ctx context.Context, cmd SessionControlCommand) (*SessionControlResult, error) {
	if err := s.store.EnsureSessionAccess(ctx, cmd.SessionID, cmd.UserID); err != nil {
		return nil, err
	}
	tasks, err := s.store.ListSessionTasks(ctx, cmd.SessionID, cmd.UserID)
	if err != nil {
		return nil, err
	}
	taskID, state, ok := resolveActiveTask(tasks)
	if !ok {
		return nil, ErrNoActiveTask
	}
	action := strings.ToLower(strings.TrimSpace(cmd.Action))
	if err := validateTransition(action, state); err != nil {
		return nil, err
	}
	signalPayload := dto.ControlSignal{
		Reason:    cmd.Reason,
		RequestBy: cmd.UserID,
		Timestamp: s.now().UTC(),
	}
	switch action {
	case "pause":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "pause", signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "paused", "")
		state = "PAUSED"
	case "resume":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "resume", signalPayload); err != nil {
			return nil, err
		}
		_ = s.store.UpdateTaskStatus(ctx, taskID, "running", "")
		state = "RUNNING"
	case "cancel":
		if err := s.runtime.SignalWorkflow(ctx, taskID, "cancel", signalPayload); err != nil {
			return nil, err
		}
		if err := s.runtime.CancelWorkflow(ctx, taskID); err != nil {
			return nil, err
		}
		state = "TERMINATING"
	default:
		return nil, fmt.Errorf("unsupported action: %s", cmd.Action)
	}

	return &SessionControlResult{
		SessionID:           cmd.SessionID,
		ActiveTaskID:        taskID,
		TaskState:           state,
		SessionControlState: controlStateFromTaskState(state),
		Accepted:            action == "cancel",
	}, nil
}

func validateTransition(action, state string) error {
	switch action {
	case "pause":
		if state != "RUNNING" {
			return fmt.Errorf("%w: active task is not running", ErrInvalidTransition)
		}
	case "resume":
		if state != "PAUSED" {
			return fmt.Errorf("%w: active task is not paused", ErrInvalidTransition)
		}
	case "cancel":
		if state != "RUNNING" && state != "PAUSED" {
			return fmt.Errorf("%w: active task is not cancellable", ErrInvalidTransition)
		}
	default:
		return fmt.Errorf("unsupported action: %s", action)
	}
	return nil
}

func resolveActiveTask(tasks []port.SessionTask) (string, string, bool) {
	if taskID, ok := resolveActiveTaskID(tasks); ok {
		for _, t := range tasks {
			if t.TaskID == taskID {
				return taskID, normalizeTaskStateForControl(t.Status), true
			}
		}
	}
	return "", "", false
}

func resolveActiveTaskID(tasks []port.SessionTask) (string, bool) {
	for i := len(tasks) - 1; i >= 0; i-- {
		st := strings.ToLower(strings.TrimSpace(tasks[i].Status))
		if st == "pending" || st == "queued" || st == "running" || st == "paused" {
			return tasks[i].TaskID, true
		}
	}
	return "", false
}

func normalizeTaskStateForControl(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "pending", "queued":
		return "QUEUED"
	case "running":
		return "RUNNING"
	case "paused":
		return "PAUSED"
	case "completed":
		return "COMPLETED"
	case "failed":
		return "FAILED"
	case "cancelled", "canceled":
		return "CANCELLED"
	default:
		return "IDLE"
	}
}

func controlStateFromTaskState(state string) string {
	switch state {
	case "QUEUED", "RUNNING":
		return "ACTIVE_RUNNING"
	case "PAUSED":
		return "ACTIVE_PAUSED"
	case "TERMINATING":
		return "TERMINATING"
	default:
		return "IDLE"
	}
}
