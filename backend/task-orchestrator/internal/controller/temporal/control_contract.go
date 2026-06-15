package temporal

import "time"

const (
	CommandSignalName = "kardcraft.task.command"
	QueryRunStatus    = "kardcraft.task.query.run-status"

	CommandPause  = "pause"
	CommandResume = "resume"
	CommandCancel = "cancel"

	LifecycleStateCanceled = "canceled"
)

type RunStatus struct {
	RunID          string
	LifecycleState string
	Step           int32
	Reason         string
	UpdatedAt      time.Time
}
