package adapters

import (
	"strings"

	"task-orchestrator/internal/runtime/temporal/workflows"
)

func DecodeTaskOutcomeMessage(payload map[string]any) (string, bool) {
	out, err := workflows.DecodeTaskOutcome(payload)
	if err != nil {
		return "", false
	}
	msg := strings.TrimSpace(out.Message)
	if msg == "" {
		return "", false
	}
	return msg, true
}
