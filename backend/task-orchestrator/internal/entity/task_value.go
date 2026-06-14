package entity

import (
	"errors"
	"strings"
)

var (
	ErrInvalidTaskID  = errors.New("invalid task id")
	ErrInvalidStepID  = errors.New("invalid step id")
	ErrInvalidStatus  = errors.New("invalid status")
	ErrEmptyStepName  = errors.New("step name cannot be empty")
	ErrEmptyFailCause = errors.New("fail reason cannot be empty")
)

type TaskID struct {
	value string
}

func NewTaskID(raw string) (TaskID, error) {
	v := strings.TrimSpace(raw)
	if v == "" {
		return TaskID{}, ErrInvalidTaskID
	}
	return TaskID{value: v}, nil
}

func (id TaskID) String() string {
	return id.value
}

func (id TaskID) Equal(other TaskID) bool {
	return id.value == other.value
}

type StepID struct {
	value string
}

func NewStepID(raw string) (StepID, error) {
	v := strings.TrimSpace(raw)
	if v == "" {
		return StepID{}, ErrInvalidStepID
	}
	return StepID{value: v}, nil
}

func (id StepID) String() string {
	return id.value
}

func (id StepID) Equal(other StepID) bool {
	return id.value == other.value
}

type Status struct {
	value string
}

var (
	statusPending   = Status{value: "pending"}
	statusRunning   = Status{value: "running"}
	statusCompleted = Status{value: "completed"}
	statusFailed    = Status{value: "failed"}
	statusPaused    = Status{value: "paused"}
	statusCancelled = Status{value: "cancelled"}
)

func NewStatus(raw string) (Status, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case statusPending.value:
		return statusPending, nil
	case statusRunning.value:
		return statusRunning, nil
	case statusCompleted.value:
		return statusCompleted, nil
	case statusFailed.value:
		return statusFailed, nil
	case statusPaused.value:
		return statusPaused, nil
	case statusCancelled.value:
		return statusCancelled, nil
	default:
		return Status{}, ErrInvalidStatus
	}
}

func MustStatus(raw string) Status {
	s, err := NewStatus(raw)
	if err != nil {
		panic(err)
	}
	return s
}

func PendingStatus() Status {
	return statusPending
}

func RunningStatus() Status {
	return statusRunning
}

func CompletedStatus() Status {
	return statusCompleted
}

func FailedStatus() Status {
	return statusFailed
}

func PausedStatus() Status {
	return statusPaused
}

func CancelledStatus() Status {
	return statusCancelled
}

func (s Status) String() string {
	return s.value
}

func (s Status) Equal(other Status) bool {
	return s.value == other.value
}
