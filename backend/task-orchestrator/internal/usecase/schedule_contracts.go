package usecase

import (
	"context"
	"time"
)

type ScheduleRecord struct {
	ScheduleID         string
	TemporalScheduleID string
	UserID             string
	Name               string
	Description        string
	CronExpression     string
	Timezone           string
	TaskQuery          string
	Status             string
	TotalRuns          int
	SuccessfulRuns     int
	FailedRuns         int
	CreatedAt          time.Time
	UpdatedAt          time.Time
}

type ScheduleRunRow struct {
	ScheduleID  string
	TaskID      string
	SessionID   string
	TriggeredAt time.Time
	Status      string
	Result      string
	Error       string
	TaskQuery   string
	StartedAt   *time.Time
	CompletedAt *time.Time
	DurationMS  *int64
	Usage       TaskUsageSummary
}

type ScheduleStore interface {
	CreateSchedule(context.Context, ScheduleRecord) error
	GetSchedule(context.Context, string, string) (*ScheduleRecord, error)
	GetScheduleByID(context.Context, string) (*ScheduleRecord, error)
	ListSchedules(context.Context, string, int, int, string) ([]ScheduleRecord, int, error)
	UpdateSchedule(context.Context, ScheduleRecord) error
	UpdateScheduleStatus(context.Context, string, string) error
	DeleteSchedule(context.Context, string, string) (int64, error)
	CreateScheduleRun(context.Context, ScheduleRunRow) error
	FailScheduleRun(context.Context, string, string) error
	ListScheduleRuns(context.Context, string, string, int, int) ([]ScheduleRunRow, int, error)
}

type ScheduleRuntime interface {
	Create(context.Context, ScheduleRecord) error
	Update(context.Context, ScheduleRecord) error
	Pause(context.Context, ScheduleRecord, string) error
	Resume(context.Context, ScheduleRecord, string) error
	Delete(context.Context, ScheduleRecord) error
}
