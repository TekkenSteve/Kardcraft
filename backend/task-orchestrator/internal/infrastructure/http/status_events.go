package httpserver

import (
	"context"

	enumspb "go.temporal.io/api/enums/v1"

	"task-orchestrator/internal/domain/task"
)

func (s *Server) isTemporalEnabled() bool {
	return s.temporal != nil
}

func mapTaskStatus(t *task.Task) string {
	switch t.Status().String() {
	case "pending":
		return "TASK_STATUS_QUEUED"
	case "running":
		return "TASK_STATUS_RUNNING"
	case "completed":
		return "TASK_STATUS_COMPLETED"
	case "failed":
		return "TASK_STATUS_FAILED"
	case "paused":
		return "TASK_STATUS_PAUSED"
	case "cancelled":
		return "TASK_STATUS_CANCELLED"
	default:
		return t.Status().String()
	}
}

func normalizeSessionState(status string) string {
	switch status {
	case "TASK_STATUS_QUEUED", "TASK_STATUS_RUNNING":
		return "running"
	case "TASK_STATUS_COMPLETED":
		return "completed"
	case "TASK_STATUS_FAILED":
		return "failed"
	case "TASK_STATUS_PAUSED":
		return "paused"
	case "TASK_STATUS_CANCELLED":
		return "cancelled"
	default:
		return "idle"
	}
}

func mapTemporalStatus(st enumspb.WorkflowExecutionStatus) string {
	switch st {
	case enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING:
		return "TASK_STATUS_RUNNING"
	case enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED:
		return "TASK_STATUS_COMPLETED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_FAILED:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_CANCELED:
		return "TASK_STATUS_CANCELLED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_TERMINATED:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
		return "TASK_STATUS_FAILED"
	case enumspb.WORKFLOW_EXECUTION_STATUS_CONTINUED_AS_NEW:
		return "TASK_STATUS_RUNNING"
	default:
		return "TASK_STATUS_QUEUED"
	}
}

func (s *Server) onDomainEvents(events []task.DomainEvent) {
	for _, ev := range events {
		workflowID := ev.AggregateID()
		taskObj, err := s.taskService.GetTask(context.Background(), workflowID)
		if err != nil {
			continue
		}
		sessionID := taskObj.SessionID()

		switch ev.EventType() {
		case task.EventTypeTaskCreated:
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "pending", "")
			}
		case task.EventTypeTaskStarted:
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			s.ensureWorkflowStreamReader(workflowID)
			s.appendTimeline(workflowID, sessionID, "WORKFLOW_STARTED", "Workflow started", nil)
		case task.EventTypeTaskCompleted:
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "completed", "")
			}
			s.appendTimeline(workflowID, sessionID, "WORKFLOW_COMPLETED", "Workflow completed", nil)
			s.appendTimeline(workflowID, sessionID, "done", "Stream end", nil)
			s.stopWorkflowStreamReader(workflowID)
		case task.EventTypeTaskFailed:
			reason := "Task failed"
			if typed, ok := ev.(task.TaskFailed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "failed", reason)
			}
			s.appendTimeline(workflowID, sessionID, "WORKFLOW_FAILED", reason, nil)
			s.stopWorkflowStreamReader(workflowID)
		case task.EventTypeTaskPaused:
			reason := "Task paused"
			if typed, ok := ev.(task.TaskPaused); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "paused", "")
			}
			s.appendTimeline(workflowID, sessionID, "workflow.paused", reason, nil)
		case task.EventTypeTaskResumed:
			reason := "Task resumed"
			if typed, ok := ev.(task.TaskResumed); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "running", "")
			}
			s.appendTimeline(workflowID, sessionID, "workflow.resumed", reason, nil)
		case task.EventTypeTaskCancelled:
			reason := "Task cancelled"
			if typed, ok := ev.(task.TaskCancelled); ok && typed.Reason() != "" {
				reason = typed.Reason()
			}
			if s.sessionDB != nil {
				_ = s.sessionDB.UpdateTaskStatus(context.Background(), workflowID, "cancelled", reason)
			}
			s.appendTimeline(workflowID, sessionID, "workflow.cancelled", reason, nil)
			s.stopWorkflowStreamReader(workflowID)
		}
	}
}
