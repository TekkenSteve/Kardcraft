package task

import (
	"errors"
	"strings"
	"time"
)

var (
	ErrStepNotPending = errors.New("step is not pending")
	ErrStepNotRunning = errors.New("step is not running")
)

type Step struct {
	id           StepID
	name         string
	status       Status
	startedAt    *time.Time
	completedAt  *time.Time
	failedAt     *time.Time
	failureCause string
}

func NewStep(id StepID, name string) (Step, error) {
	n := strings.TrimSpace(name)
	if n == "" {
		return Step{}, ErrEmptyStepName
	}
	return Step{
		id:     id,
		name:   n,
		status: PendingStatus(),
	}, nil
}

func RestoreStep(
	id StepID,
	name string,
	status Status,
	startedAt *time.Time,
	completedAt *time.Time,
	failedAt *time.Time,
	failureCause string,
) Step {
	copyStarted := cloneTimePtr(startedAt)
	copyCompleted := cloneTimePtr(completedAt)
	copyFailed := cloneTimePtr(failedAt)
	return Step{
		id:           id,
		name:         name,
		status:       status,
		startedAt:    copyStarted,
		completedAt:  copyCompleted,
		failedAt:     copyFailed,
		failureCause: failureCause,
	}
}

func (s *Step) Start(now time.Time) error {
	if !s.status.Equal(PendingStatus()) {
		return ErrStepNotPending
	}
	s.status = RunningStatus()
	t := now.UTC()
	s.startedAt = &t
	s.completedAt = nil
	s.failedAt = nil
	s.failureCause = ""
	return nil
}

func (s *Step) Complete(now time.Time) error {
	if !s.status.Equal(RunningStatus()) {
		return ErrStepNotRunning
	}
	s.status = CompletedStatus()
	t := now.UTC()
	s.completedAt = &t
	s.failedAt = nil
	s.failureCause = ""
	return nil
}

func (s *Step) Fail(now time.Time, cause string) error {
	if !s.status.Equal(RunningStatus()) {
		return ErrStepNotRunning
	}
	reason := strings.TrimSpace(cause)
	if reason == "" {
		return ErrEmptyFailCause
	}
	s.status = FailedStatus()
	t := now.UTC()
	s.failedAt = &t
	s.completedAt = nil
	s.failureCause = reason
	return nil
}

func (s Step) ID() StepID {
	return s.id
}

func (s Step) Name() string {
	return s.name
}

func (s Step) Status() Status {
	return s.status
}

func (s Step) StartedAt() *time.Time {
	return cloneTimePtr(s.startedAt)
}

func (s Step) CompletedAt() *time.Time {
	return cloneTimePtr(s.completedAt)
}

func (s Step) FailedAt() *time.Time {
	return cloneTimePtr(s.failedAt)
}

func (s Step) FailureCause() string {
	return s.failureCause
}
