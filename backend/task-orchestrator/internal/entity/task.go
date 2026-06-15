package entity

import (
	"errors"
	"strings"
	"time"
)

var (
	ErrTaskAlreadyStarted = errors.New("task cannot start from current status")
	ErrTaskNotRunning     = errors.New("task is not running")
	ErrTaskNotPaused      = errors.New("task is not paused")
	ErrTaskNotCancelable  = errors.New("task cannot be cancelled from current status")
)

type Task struct {
	id           TaskID
	status       Status
	taskType     string
	userID       string
	query        string
	sessionID    string
	createdAt    time.Time
	updatedAt    time.Time
	startedAt    *time.Time
	completedAt  *time.Time
	failedAt     *time.Time
	failureCause string
	pausedAt     *time.Time
	pauseReason  string
	cancelledAt  *time.Time
	cancelReason string
	events       []DomainEvent
}

func NewTask(id TaskID, taskType, userID, query, sessionID string, now time.Time) *Task {
	typeValue := strings.TrimSpace(taskType)
	if typeValue == "" {
		typeValue = "main"
	}
	ts := now.UTC()
	t := &Task{
		id:        id,
		status:    PendingStatus(),
		taskType:  typeValue,
		userID:    strings.TrimSpace(userID),
		query:     strings.TrimSpace(query),
		sessionID: strings.TrimSpace(sessionID),
		createdAt: ts,
		updatedAt: ts,
	}
	t.recordEvent(newTaskCreatedEvent(id, ts))
	return t
}

func RestoreTask(snapshot TaskSnapshot) *Task {
	return &Task{
		id:           snapshot.ID,
		status:       snapshot.Status,
		taskType:     snapshot.TaskType,
		userID:       snapshot.UserID,
		query:        snapshot.Query,
		sessionID:    snapshot.SessionID,
		createdAt:    snapshot.CreatedAt,
		updatedAt:    snapshot.UpdatedAt,
		startedAt:    cloneTimePtr(snapshot.StartedAt),
		completedAt:  cloneTimePtr(snapshot.CompletedAt),
		failedAt:     cloneTimePtr(snapshot.FailedAt),
		failureCause: snapshot.FailureCause,
		pausedAt:     cloneTimePtr(snapshot.PausedAt),
		pauseReason:  snapshot.PauseReason,
		cancelledAt:  cloneTimePtr(snapshot.CancelledAt),
		cancelReason: snapshot.CancelReason,
	}
}

func (t *Task) Start(now time.Time) error {
	if !t.status.Equal(PendingStatus()) {
		return ErrTaskAlreadyStarted
	}
	ts := now.UTC()
	t.status = RunningStatus()
	t.startedAt = &ts
	t.updatedAt = ts
	t.completedAt = nil
	t.failedAt = nil
	t.failureCause = ""
	t.pausedAt = nil
	t.pauseReason = ""
	t.cancelledAt = nil
	t.cancelReason = ""

	t.recordEvent(newTaskStartedEvent(t.id, ts))
	return nil
}

func (t *Task) Complete(now time.Time) error {
	if !t.status.Equal(RunningStatus()) {
		return ErrTaskNotRunning
	}
	ts := now.UTC()
	t.status = CompletedStatus()
	t.updatedAt = ts
	t.completedAt = &ts
	t.failedAt = nil
	t.failureCause = ""
	t.pausedAt = nil
	t.pauseReason = ""
	t.cancelledAt = nil
	t.cancelReason = ""
	t.recordEvent(newTaskCompletedEvent(t.id, ts))
	return nil
}

func (t *Task) Fail(now time.Time, reason string) error {
	if !t.status.Equal(RunningStatus()) {
		return ErrTaskNotRunning
	}
	r := strings.TrimSpace(reason)
	if r == "" {
		return ErrEmptyFailCause
	}
	ts := now.UTC()
	t.status = FailedStatus()
	t.updatedAt = ts
	t.failedAt = &ts
	t.failureCause = r
	t.completedAt = nil
	t.pausedAt = nil
	t.pauseReason = ""
	t.cancelledAt = nil
	t.cancelReason = ""
	t.recordEvent(newTaskFailedEvent(t.id, ts, r))
	return nil
}

func (t *Task) Pause(now time.Time, reason string) error {
	if !t.status.Equal(RunningStatus()) {
		return ErrTaskNotRunning
	}
	ts := now.UTC()
	r := strings.TrimSpace(reason)
	if r == "" {
		r = "manual pause"
	}
	t.status = PausedStatus()
	t.updatedAt = ts
	t.pausedAt = &ts
	t.pauseReason = r
	t.recordEvent(newTaskPausedEvent(t.id, ts, r))
	return nil
}

func (t *Task) Resume(now time.Time, reason string) error {
	if !t.status.Equal(PausedStatus()) {
		return ErrTaskNotPaused
	}
	ts := now.UTC()
	r := strings.TrimSpace(reason)
	if r == "" {
		r = "manual resume"
	}
	t.status = RunningStatus()
	t.updatedAt = ts
	t.pausedAt = nil
	t.pauseReason = ""
	t.recordEvent(newTaskResumedEvent(t.id, ts, r))
	return nil
}

func (t *Task) Cancel(now time.Time, reason string) error {
	if !t.status.Equal(PendingStatus()) && !t.status.Equal(RunningStatus()) && !t.status.Equal(PausedStatus()) {
		return ErrTaskNotCancelable
	}
	ts := now.UTC()
	r := strings.TrimSpace(reason)
	if r == "" {
		r = "manual cancel"
	}
	t.status = CancelledStatus()
	t.updatedAt = ts
	t.cancelledAt = &ts
	t.cancelReason = r
	t.completedAt = nil
	t.failedAt = nil
	t.failureCause = ""
	t.pausedAt = nil
	t.pauseReason = ""
	t.recordEvent(newTaskCancelledEvent(t.id, ts, r))
	return nil
}

func (t *Task) PullEvents() []DomainEvent {
	if len(t.events) == 0 {
		return nil
	}
	out := make([]DomainEvent, len(t.events))
	copy(out, t.events)
	t.events = t.events[:0]
	return out
}

func (t *Task) Snapshot() TaskSnapshot {
	return TaskSnapshot{
		ID:           t.id,
		Status:       t.status,
		TaskType:     t.taskType,
		UserID:       t.userID,
		Query:        t.query,
		SessionID:    t.sessionID,
		CreatedAt:    t.createdAt,
		UpdatedAt:    t.updatedAt,
		StartedAt:    cloneTimePtr(t.startedAt),
		CompletedAt:  cloneTimePtr(t.completedAt),
		FailedAt:     cloneTimePtr(t.failedAt),
		FailureCause: t.failureCause,
		PausedAt:     cloneTimePtr(t.pausedAt),
		PauseReason:  t.pauseReason,
		CancelledAt:  cloneTimePtr(t.cancelledAt),
		CancelReason: t.cancelReason,
	}
}

func (t *Task) ID() TaskID {
	return t.id
}

func (t *Task) Status() Status {
	return t.status
}

func (t *Task) TaskType() string {
	return t.taskType
}

func (t *Task) UserID() string {
	return t.userID
}

func (t *Task) Query() string {
	return t.query
}

func (t *Task) SessionID() string {
	return t.sessionID
}

func (t *Task) CreatedAt() time.Time {
	return t.createdAt
}

func (t *Task) UpdatedAt() time.Time {
	return t.updatedAt
}

func (t *Task) StartedAt() *time.Time {
	return cloneTimePtr(t.startedAt)
}

func (t *Task) CompletedAt() *time.Time {
	return cloneTimePtr(t.completedAt)
}

func (t *Task) FailedAt() *time.Time {
	return cloneTimePtr(t.failedAt)
}

func (t *Task) FailureCause() string {
	return t.failureCause
}

func (t *Task) PausedAt() *time.Time {
	return cloneTimePtr(t.pausedAt)
}

func (t *Task) PauseReason() string {
	return t.pauseReason
}

func (t *Task) CancelledAt() *time.Time {
	return cloneTimePtr(t.cancelledAt)
}

func (t *Task) CancelReason() string {
	return t.cancelReason
}

func (t *Task) recordEvent(event DomainEvent) {
	t.events = append(t.events, event)
}

type TaskSnapshot struct {
	ID           TaskID
	Status       Status
	TaskType     string
	UserID       string
	Query        string
	SessionID    string
	CreatedAt    time.Time
	UpdatedAt    time.Time
	StartedAt    *time.Time
	CompletedAt  *time.Time
	FailedAt     *time.Time
	FailureCause string
	PausedAt     *time.Time
	PauseReason  string
	CancelledAt  *time.Time
	CancelReason string
}

func cloneTimePtr(src *time.Time) *time.Time {
	if src == nil {
		return nil
	}
	v := src.UTC()
	return &v
}
