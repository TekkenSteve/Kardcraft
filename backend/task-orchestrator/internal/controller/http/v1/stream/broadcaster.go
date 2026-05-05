package stream

import "encoding/json"

type Broadcaster struct{}

func NewBroadcaster() *Broadcaster {
	return &Broadcaster{}
}

func (b *Broadcaster) BuildEventPayload(
	schemaVersion int,
	correlationID string,
	eventID string,
	workflowID string,
	runID string,
	sessionID string,
	occurredAt string,
	eventType string,
	streamID string,
	payload map[string]any,
) ([]byte, error) {
	body := map[string]any{
		"schema_version": schemaVersion,
		"correlation_id": correlationID,
		"event_id":       eventID,
		"event_type":  eventType,
		"workflow_id": workflowID,
		"run_id":      runID,
		"session_id":  sessionID,
		"occurred_at": occurredAt,
		"stream_id":   streamID,
	}
	body["payload"] = payload
	return json.Marshal(body)
}
