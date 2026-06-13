package restapi

import (
	"strings"

	"task-orchestrator/internal/controller/temporal"
)

func DecodeTaskOutcomeMessage(payload map[string]any) (string, bool) {
	out, err := temporal.DecodeTaskOutcome(payload)
	if err != nil {
		return "", false
	}
	msg := strings.TrimSpace(out.Message)
	if msg == "" {
		return "", false
	}
	return msg, true
}
