package entity

import (
	"fmt"
	"sync/atomic"
	"time"

	"github.com/TekkenSteve/GoAgent/entity"
)

type DomainEvent interface {
	EventID() string
	EventType() string
	AggregateID() string
	OccurredAt() time.Time
}

type taskEvent struct {
	entity.BaseEvent
	aggregateID string
}

func (e taskEvent) EventID() string {
	return e.BaseEvent.EventID
}

func (e taskEvent) EventType() string {
	return e.BaseEvent.EventType
}

func (e taskEvent) AggregateID() string {
	return e.aggregateID
}

func (e taskEvent) OccurredAt() time.Time {
	return e.BaseEvent.Timestamp
}

type TaskCreated struct{ taskEvent }
type TaskStarted struct{ taskEvent }
type TaskCompleted struct{ taskEvent }
type TaskPaused struct {
	taskEvent
	reason string
}
type TaskResumed struct {
	taskEvent
	reason string
}
type TaskCancelled struct {
	taskEvent
	reason string
}
type TaskFailed struct {
	taskEvent
	reason string
}

func (e TaskPaused) Reason() string {
	return e.reason
}

func (e TaskResumed) Reason() string {
	return e.reason
}

func (e TaskCancelled) Reason() string {
	return e.reason
}

func (e TaskFailed) Reason() string {
	return e.reason
}

const (
	EventTypeTaskCreated   = "task.created"
	EventTypeTaskStarted   = "task.started"
	EventTypeTaskCompleted = "task.completed"
	EventTypeTaskPaused    = "task.paused"
	EventTypeTaskResumed   = "task.resumed"
	EventTypeTaskCancelled = "task.cancelled"
	EventTypeTaskFailed    = "task.failed"
)

var eventSeq uint64

func newTaskCreatedEvent(taskID TaskID, at time.Time) TaskCreated {
	return TaskCreated{taskEvent: baseTaskEvent(EventTypeTaskCreated, taskID, at)}
}

func newTaskStartedEvent(taskID TaskID, at time.Time) TaskStarted {
	return TaskStarted{taskEvent: baseTaskEvent(EventTypeTaskStarted, taskID, at)}
}

func newTaskCompletedEvent(taskID TaskID, at time.Time) TaskCompleted {
	return TaskCompleted{taskEvent: baseTaskEvent(EventTypeTaskCompleted, taskID, at)}
}

func newTaskPausedEvent(taskID TaskID, at time.Time, reason string) TaskPaused {
	return TaskPaused{taskEvent: baseTaskEvent(EventTypeTaskPaused, taskID, at), reason: reason}
}

func newTaskResumedEvent(taskID TaskID, at time.Time, reason string) TaskResumed {
	return TaskResumed{taskEvent: baseTaskEvent(EventTypeTaskResumed, taskID, at), reason: reason}
}

func newTaskCancelledEvent(taskID TaskID, at time.Time, reason string) TaskCancelled {
	return TaskCancelled{taskEvent: baseTaskEvent(EventTypeTaskCancelled, taskID, at), reason: reason}
}

func newTaskFailedEvent(taskID TaskID, at time.Time, reason string) TaskFailed {
	return TaskFailed{taskEvent: baseTaskEvent(EventTypeTaskFailed, taskID, at), reason: reason}
}

func baseTaskEvent(eventType string, taskID TaskID, at time.Time) taskEvent {
	ts := at.UTC()
	seq := atomic.AddUint64(&eventSeq, 1)
	return taskEvent{
		BaseEvent: entity.BaseEvent{
			EventID:   fmt.Sprintf("%s-%s-%d", eventType, taskID.String(), seq),
			EventType: eventType,
			Timestamp: ts,
		},
		aggregateID: taskID.String(),
	}
}
