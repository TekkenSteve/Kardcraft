package support

import (
	"context"

	"task-orchestrator/internal/entity/task"
	"task-orchestrator/internal/usecase"
)

type DomainProjectionDeps struct {
	TaskService                *usecase.TaskService
	ReadModel                  *usecase.ReadModelService
	EnsureWorkflowStreamReader func(workflowID string)
	StopWorkflowStreamReader   func(workflowID string)
	AppendTimeline             func(workflowID, sessionID, eventType, message string, payload any)
}

func domainRuntimePayload(ev task.DomainEvent, workflowID string) map[string]any {
	return map[string]any{
		"task_id":        workflowID,
		"workflow_id":    workflowID,
		"correlation_id": ev.EventID(),
		"domain_event":   ev.EventType(),
	}
}

func ProjectDomainEvents(events []task.DomainEvent, deps DomainProjectionDeps) {
	for _, ev := range events {
		workflowID := ev.AggregateID()
		taskObj, err := deps.TaskService.GetTask(context.Background(), workflowID)
		if err != nil {
			continue
		}
		sessionID := taskObj.SessionID()
		runtimePayload := domainRuntimePayload(ev, workflowID)

		switch ev.EventType() {
		case task.EventTypeTaskCreated:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "pending", "")
			}
		case task.EventTypeTaskStarted:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			deps.EnsureWorkflowStreamReader(workflowID)
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_STARTED", "Workflow started", runtimePayload)
		case task.EventTypeTaskCompleted:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "completed", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_COMPLETED", "Workflow completed", runtimePayload)
			deps.AppendTimeline(workflowID, sessionID, "done", "Stream end", runtimePayload)
			deps.StopWorkflowStreamReader(workflowID)
		case task.EventTypeTaskFailed:
			reason := "Task failed"
			if typed, ok := ev.(task.TaskFailed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "failed", reason)
			}
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_FAILED", reason, runtimePayload)
			deps.StopWorkflowStreamReader(workflowID)
		case task.EventTypeTaskPaused:
			reason := "Task paused"
			if typed, ok := ev.(task.TaskPaused); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "paused", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "workflow.paused", reason, runtimePayload)
		case task.EventTypeTaskResumed:
			reason := "Task resumed"
			if typed, ok := ev.(task.TaskResumed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "workflow.resumed", reason, runtimePayload)
		case task.EventTypeTaskCancelled:
			reason := "Task cancelled"
			if typed, ok := ev.(task.TaskCancelled); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "cancelled", reason)
			}
			deps.AppendTimeline(workflowID, sessionID, "workflow.cancelled", reason, runtimePayload)
			deps.StopWorkflowStreamReader(workflowID)
		}
	}
}
