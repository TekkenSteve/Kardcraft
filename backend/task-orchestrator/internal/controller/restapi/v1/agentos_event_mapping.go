package v1

import (
	"strings"

	"task-orchestrator/internal/usecase"
)

var agentOSRuntimeEventTypes = map[string]string{
	"run.started":             usecase.EventWorkflowStarted,
	"run.completed":           usecase.EventWorkflowCompleted,
	"run.failed":              usecase.EventWorkflowFailed,
	"run.cancelled":           usecase.EventWorkflowCancelled,
	"run.paused":              usecase.EventWorkflowPaused,
	"run.resumed":             usecase.EventWorkflowResumed,
	"agent.message.delta":     usecase.EventThreadMessageDelta,
	"agent.message.completed": usecase.EventThreadMessageCompleted,
	"approval.requested":      usecase.EventWorkflowWaitingInput,
	"usage.reported":          usecase.EventLLMUsageRecorded,
}

func kardcraftEventTypeFromAgentOS(eventType string) string {
	normalized := strings.TrimSpace(eventType)
	if normalized == "" {
		return usecase.EventWorkflowProgress
	}
	if mapped, ok := agentOSRuntimeEventTypes[normalized]; ok {
		return mapped
	}
	return normalized
}
