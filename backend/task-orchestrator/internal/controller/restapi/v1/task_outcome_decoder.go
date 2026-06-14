package v1

import (
	"strings"

	"task-orchestrator/internal/usecase/outcome"
)

func DecodeTaskOutcomeMessage(payload map[string]any) (string, bool) {
	out, err := outcome.DecodeTaskOutcome(payload)
	if err != nil {
		return "", false
	}
	msg := strings.TrimSpace(out.Message)
	if msg == "" {
		return "", false
	}
	return msg, true
}
