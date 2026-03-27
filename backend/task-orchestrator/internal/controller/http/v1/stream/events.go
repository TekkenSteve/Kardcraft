package stream

type OutboundEvent struct {
	ID      int64
	Event   string
	Payload []byte
}
