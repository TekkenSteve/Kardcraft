package stream

import "encoding/json"

type Broadcaster struct{}

func NewBroadcaster() *Broadcaster {
	return &Broadcaster{}
}

func (b *Broadcaster) BuildEventPayload(evType, workflowID, taskID, message, timestamp, streamID string, payload map[string]any) ([]byte, error) {
	body := map[string]any{
		"type":        evType,
		"workflow_id": workflowID,
		"task_id":     taskID,
		"message":     message,
		"timestamp":   timestamp,
		"stream_id":   streamID,
	}
	if payload != nil {
		body["payload"] = payload
	}
	return json.Marshal(body)
}
