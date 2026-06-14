package v1

import (
	"context"

	"task-orchestrator/internal/entity"
	"task-orchestrator/internal/usecase"
)

type DomainProjectionDeps struct {
	TaskService                usecase.Task
	ReadModel                  usecase.ReadModel
	EnsureWorkflowStreamReader func(workflowID string)
	StopWorkflowStreamReader   func(workflowID string)
	AppendTimeline             func(workflowID, sessionID, eventType, message string, payload any)
}

func domainRuntimePayload(ev entity.DomainEvent, workflowID string) map[string]any {
	return map[string]any{
		"task_id":        workflowID,
		"workflow_id":    workflowID,
		"correlation_id": ev.EventID(),
		"domain_event":   ev.EventType(),
	}
}

func ProjectDomainEvents(events []entity.DomainEvent, deps DomainProjectionDeps) {
	for _, ev := range events {
		workflowID := ev.AggregateID()
		taskObj, err := deps.TaskService.GetTask(context.Background(), workflowID)
		if err != nil {
			continue
		}
		sessionID := taskObj.SessionID()
		runtimePayload := domainRuntimePayload(ev, workflowID)

		switch ev.EventType() {
		case entity.EventTypeTaskCreated:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "pending", "")
			}
		case entity.EventTypeTaskStarted:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			deps.EnsureWorkflowStreamReader(workflowID)
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_STARTED", "Workflow started", runtimePayload)
		case entity.EventTypeTaskCompleted:
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "completed", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_COMPLETED", "Workflow completed", runtimePayload)
			deps.AppendTimeline(workflowID, sessionID, "done", "Stream end", runtimePayload)
			deps.StopWorkflowStreamReader(workflowID)
		case entity.EventTypeTaskFailed:
			reason := "Task failed"
			if typed, ok := ev.(entity.TaskFailed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "failed", reason)
			}
			deps.AppendTimeline(workflowID, sessionID, "WORKFLOW_FAILED", reason, runtimePayload)
			deps.StopWorkflowStreamReader(workflowID)
		case entity.EventTypeTaskPaused:
			reason := "Task paused"
			if typed, ok := ev.(entity.TaskPaused); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "paused", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "workflow.paused", reason, runtimePayload)
		case entity.EventTypeTaskResumed:
			reason := "Task resumed"
			if typed, ok := ev.(entity.TaskResumed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if deps.ReadModel != nil {
				_ = deps.ReadModel.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			deps.AppendTimeline(workflowID, sessionID, "workflow.resumed", reason, runtimePayload)
		case entity.EventTypeTaskCancelled:
			reason := "Task cancelled"
			if typed, ok := ev.(entity.TaskCancelled); ok && typed.Reason() != "" {
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
