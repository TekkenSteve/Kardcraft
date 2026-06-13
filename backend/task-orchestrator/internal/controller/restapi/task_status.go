package restapi

import "task-orchestrator/internal/entity"

func MapTaskStatus(t *entity.Task) string {
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

func NormalizeSessionState(status string) string {
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
