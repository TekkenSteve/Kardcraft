// Package execution provides Kardcraft's durable task-execution application
// services. It intentionally depends only on the local TaskExecution port.
package execution

import (
	"context"
	"fmt"
	"strings"

	"task-orchestrator/internal/usecase"
)

// Feed exposes durable replay followed by live task-execution events. The
// underlying execution runtime owns event ordering and cursor semantics.
type Feed struct {
	execution usecase.TaskExecution
}

func NewFeed(execution usecase.TaskExecution) (*Feed, error) {
	if execution == nil {
		return nil, fmt.Errorf("task execution is required")
	}

	return &Feed{execution: execution}, nil
}

func (f *Feed) Subscribe(ctx context.Context, taskID string, afterSequence int64) (usecase.TaskExecutionSubscription, error) {
	if f == nil || f.execution == nil {
		return nil, fmt.Errorf("task execution is required")
	}
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return nil, fmt.Errorf("task id is required")
	}
	if afterSequence < 0 {
		return nil, fmt.Errorf("event sequence cannot be negative")
	}

	return f.execution.SubscribeTaskExecution(ctx, usecase.TaskExecutionEventScope{
		TaskID:        taskID,
		AfterSequence: afterSequence,
	})
}
