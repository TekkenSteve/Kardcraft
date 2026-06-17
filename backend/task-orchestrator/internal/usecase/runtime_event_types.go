package usecase

const (
	EventThreadMessageDelta     = "thread.message.delta"
	EventThreadMessageCompleted = "thread.message.completed"
	EventStreamEnd              = "STREAM_END"
	EventDone                   = "done"
	EventError                  = "error"

	EventWorkflowStarted      = "WORKFLOW_STARTED"
	EventWorkflowProgress     = "WORKFLOW_PROGRESS"
	EventWorkflowWaitingInput = "WORKFLOW_WAITING_INPUT"
	EventWorkflowPaused       = "WORKFLOW_PAUSED"
	EventWorkflowResumed      = "WORKFLOW_RESUMED"
	EventWorkflowCancelling   = "WORKFLOW_CANCELLING"
	EventWorkflowCompleted    = "WORKFLOW_COMPLETED"
	EventWorkflowFailed       = "WORKFLOW_FAILED"
	EventWorkflowCancelled    = "WORKFLOW_CANCELLED"

	EventMessageReceived  = "MESSAGE_RECEIVED"
	EventWorkspaceUpdated = "WORKSPACE_UPDATED"
	EventLLMUsageRecorded = "LLM_USAGE_RECORDED"
	EventLLMOutput        = "LLM_OUTPUT"
)
