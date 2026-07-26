package execution

import (
	"strings"

	"task-orchestrator/internal/usecase"
)

var agentOSEventTypes = map[string]string{
	"run.started":                 usecase.EventWorkflowStarted,
	"run.completed":               usecase.EventWorkflowCompleted,
	"run.failed":                  usecase.EventWorkflowFailed,
	"run.cancelled":               usecase.EventWorkflowCancelled,
	"run.paused":                  usecase.EventWorkflowPaused,
	"run.resumed":                 usecase.EventWorkflowResumed,
	"agent.message.delta":         usecase.EventThreadMessageDelta,
	"agent.message.completed":     usecase.EventThreadMessageCompleted,
	"approval.requested":          usecase.EventWorkflowWaitingInput,
	"usage.reported":              usecase.EventLLMUsageRecorded,
	"RUN_STARTED":                 usecase.EventWorkflowStarted,
	"RUN_ERROR":                   usecase.EventWorkflowFailed,
	"kardcraft.process.cancelled": usecase.EventWorkflowCancelled,
}

func projectedEventType(event usecase.TaskExecutionEvent) string {
	if strings.TrimSpace(event.EventType) != usecase.ConversationEventRunFinished {
		return KardcraftEventType(event.EventType)
	}
	switch strings.ToLower(stringValue(event.Payload["outcome"])) {
	case "interrupt":
		return usecase.EventWorkflowWaitingInput
	case "cancelled", "canceled":
		return usecase.EventWorkflowCancelled
	default:
		return usecase.EventWorkflowCompleted
	}
}

func KardcraftEventType(eventType string) string {
	normalized := strings.TrimSpace(eventType)
	if normalized == "" {
		return usecase.EventWorkflowProgress
	}
	if mapped, ok := agentOSEventTypes[normalized]; ok {
		return mapped
	}
	return normalized
}
