package dto

import "time"

type WorkflowDescription struct {
	WorkflowID string
	RunID      string
	Status     string
	StartTime  time.Time
	CloseTime  *time.Time
}

type WorkflowState struct {
	IsPaused     bool
	IsCancelled  bool
	PausedAt     *time.Time
	PauseReason  string
	CancelReason string
}

type WorkflowHistoryEvent struct {
	EventID   int64
	EventType string
	Timestamp time.Time
}
