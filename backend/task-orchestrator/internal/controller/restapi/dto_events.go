package restapi

type OutboundEvent struct {
	ID      int64
	Event   string
	Payload []byte
}

type NormalizedEvent struct {
	WorkflowID string
	SessionID  string
	TaskID     string
	EventType  string
	Message    string
	StreamID   string
	Payload    map[string]any
}
