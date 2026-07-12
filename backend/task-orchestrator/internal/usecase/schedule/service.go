package schedule

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"github.com/robfig/cron"
	"task-orchestrator/internal/usecase"
)

type Service struct {
	store     usecase.ScheduleStore
	runtime   usecase.ScheduleRuntime
	command   usecase.Command
	readModel ReadModel
	now       func() time.Time
}

type ReadModel interface {
	GetResolvedDefaultTemplate(context.Context, string) (*usecase.TemplateCatalogRow, error)
	GetTaskUsageSummaryMapByTaskIDs(context.Context, string, []string) (map[string]usecase.TaskUsageSummary, error)
}

type CreateInput struct {
	UserID, Name, Description, CronExpression, Timezone, TaskQuery string
}

type UpdateInput struct {
	ScheduleID, UserID                                     string
	Name, Description, CronExpression, Timezone, TaskQuery *string
}

func New(store usecase.ScheduleStore, runtime usecase.ScheduleRuntime, command usecase.Command, readModel ReadModel) *Service {
	return &Service{store: store, runtime: runtime, command: command, readModel: readModel, now: time.Now}
}

func (s *Service) Create(ctx context.Context, input CreateInput) (*usecase.ScheduleRecord, error) {
	row, err := scheduleRecord(input.UserID, input.Name, input.Description, input.CronExpression, input.Timezone, input.TaskQuery)
	if err != nil {
		return nil, err
	}
	if err := s.store.CreateSchedule(ctx, row); err != nil {
		return nil, err
	}
	if err := s.runtime.Create(ctx, row); err != nil {
		_, _ = s.store.DeleteSchedule(ctx, row.ScheduleID, row.UserID)
		return nil, err
	}
	return &row, nil
}

func (s *Service) Update(ctx context.Context, input UpdateInput) (*usecase.ScheduleRecord, error) {
	row, err := s.store.GetSchedule(ctx, input.ScheduleID, input.UserID)
	if err != nil {
		return nil, err
	}
	if input.Name != nil {
		row.Name = strings.TrimSpace(*input.Name)
	}
	if input.Description != nil {
		row.Description = strings.TrimSpace(*input.Description)
	}
	if input.CronExpression != nil {
		row.CronExpression = strings.TrimSpace(*input.CronExpression)
	}
	if input.Timezone != nil {
		row.Timezone = strings.TrimSpace(*input.Timezone)
	}
	if input.TaskQuery != nil {
		row.TaskQuery = strings.TrimSpace(*input.TaskQuery)
	}
	if err := validate(row); err != nil {
		return nil, err
	}
	if err := s.runtime.Update(ctx, *row); err != nil {
		return nil, err
	}
	if err := s.store.UpdateSchedule(ctx, *row); err != nil {
		return nil, err
	}
	return row, nil
}

func (s *Service) Pause(ctx context.Context, scheduleID, userID, reason string) (*usecase.ScheduleRecord, error) {
	row, err := s.store.GetSchedule(ctx, scheduleID, userID)
	if err != nil {
		return nil, err
	}
	if err := s.runtime.Pause(ctx, *row, reason); err != nil {
		return nil, err
	}
	if err := s.store.UpdateScheduleStatus(ctx, row.ScheduleID, "paused"); err != nil {
		return nil, err
	}
	row.Status = "paused"
	return row, nil
}

func (s *Service) Resume(ctx context.Context, scheduleID, userID, reason string) (*usecase.ScheduleRecord, error) {
	row, err := s.store.GetSchedule(ctx, scheduleID, userID)
	if err != nil {
		return nil, err
	}
	if err := s.runtime.Resume(ctx, *row, reason); err != nil {
		return nil, err
	}
	if err := s.store.UpdateScheduleStatus(ctx, row.ScheduleID, "active"); err != nil {
		return nil, err
	}
	row.Status = "active"
	return row, nil
}

func (s *Service) Delete(ctx context.Context, scheduleID, userID string) error {
	row, err := s.store.GetSchedule(ctx, scheduleID, userID)
	if err != nil {
		return err
	}
	if err := s.runtime.Delete(ctx, *row); err != nil {
		return err
	}
	_, err = s.store.DeleteSchedule(ctx, scheduleID, userID)
	return err
}

// Reconcile projects the application-owned schedule declarations into the
// trigger runtime. Apply semantics make this safe at every process start.
func (s *Service) Reconcile(ctx context.Context) error {
	rows, err := s.store.ListAllSchedules(ctx)
	if err != nil {
		return err
	}
	for i := range rows {
		if err := s.runtime.Create(ctx, rows[i]); err != nil {
			return fmt.Errorf("reconcile schedule %q: %w", rows[i].ScheduleID, err)
		}
	}

	return nil
}

func (s *Service) Get(ctx context.Context, scheduleID, userID string) (*usecase.ScheduleRecord, error) {
	return s.store.GetSchedule(ctx, scheduleID, userID)
}

func (s *Service) List(ctx context.Context, userID string, limit, offset int, status string) ([]usecase.ScheduleRecord, int, error) {
	return s.store.ListSchedules(ctx, userID, limit, offset, status)
}

func (s *Service) Runs(ctx context.Context, scheduleID, userID string, limit, offset int) ([]usecase.ScheduleRunRow, int, error) {
	rows, total, err := s.store.ListScheduleRuns(ctx, scheduleID, userID, limit, offset)
	if err != nil || s.readModel == nil || len(rows) == 0 {
		return rows, total, err
	}
	taskIDs := make([]string, 0, len(rows))
	for _, row := range rows {
		taskIDs = append(taskIDs, row.TaskID)
	}
	usage, err := s.readModel.GetTaskUsageSummaryMapByTaskIDs(ctx, userID, taskIDs)
	if err != nil {
		return nil, 0, err
	}
	for i := range rows {
		rows[i].Usage = usage[rows[i].TaskID]
	}
	return rows, total, nil
}

func scheduleRecord(userID, name, description, expression, timezone, query string) (usecase.ScheduleRecord, error) {
	id, err := newID("schedule_")
	if err != nil {
		return usecase.ScheduleRecord{}, err
	}
	row := usecase.ScheduleRecord{ScheduleID: id, UserID: strings.TrimSpace(userID), Name: strings.TrimSpace(name), Description: strings.TrimSpace(description), CronExpression: strings.TrimSpace(expression), Timezone: strings.TrimSpace(timezone), TaskQuery: strings.TrimSpace(query), Status: "active"}
	if row.Timezone == "" {
		row.Timezone = "UTC"
	}
	return row, validate(&row)
}

func validate(row *usecase.ScheduleRecord) error {
	if row.UserID == "" || row.Name == "" || row.TaskQuery == "" {
		return fmt.Errorf("user_id, name, and task_query are required")
	}
	if _, err := time.LoadLocation(row.Timezone); err != nil {
		return fmt.Errorf("invalid timezone: %w", err)
	}
	if _, err := cron.ParseStandard(row.CronExpression); err != nil {
		return fmt.Errorf("invalid cron_expression: %w", err)
	}
	return nil
}

func newID(prefix string) (string, error) {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(b), nil
}

func (s *Service) Dispatch(ctx context.Context, delivery usecase.ScheduleDelivery) error {
	if delivery.DeliveryID == "" || delivery.ScheduleID == "" || delivery.UserID == "" || delivery.ProjectID == "" || delivery.TriggeredAt.IsZero() {
		return fmt.Errorf("schedule delivery is incomplete")
	}

	row, err := s.store.GetScheduleByID(ctx, delivery.ScheduleID)
	if err != nil {
		return err
	}
	if !matchesScheduleDelivery(*row, delivery) {
		return fmt.Errorf("trigger delivery does not match schedule scope")
	}
	if row.Status != "active" {
		return nil
	}
	if s.command == nil || s.readModel == nil {
		return fmt.Errorf("schedule dispatcher is not configured")
	}
	sessionID := deliveryScopedID("schedule_session_", delivery.DeliveryID)
	taskID := deliveryScopedID("workflow_schedule_", delivery.DeliveryID)
	if _, err := s.store.CreateScheduleRun(ctx, usecase.ScheduleRunRow{
		DeliveryID:  delivery.DeliveryID,
		ScheduleID:  row.ScheduleID,
		TaskID:      taskID,
		SessionID:   sessionID,
		Status:      "dispatching",
		TriggeredAt: delivery.TriggeredAt,
	}); err != nil {
		return err
	}
	template, err := s.readModel.GetResolvedDefaultTemplate(ctx, row.UserID)
	if err != nil {
		return s.failDispatch(ctx, taskID, fmt.Errorf("schedule requires an accessible default template: %w", err))
	}
	_, _, err = s.command.CreateTaskInSession(ctx, usecase.CreateTaskCommand{
		TaskID: taskID, UserID: row.UserID, TaskType: usecase.TaskTypeMain, SessionID: sessionID, Query: row.TaskQuery,
		Input:    usecase.AgentTaskInput{SessionID: sessionID, Query: row.TaskQuery, Context: usecase.TemplateContext{TemplateID: template.DefaultTemplateID, TemplateVersion: template.DefaultTemplateVersion}},
		Metadata: usecase.CreateTaskMetadata{RequestID: delivery.DeliveryID, Source: "schedule"},
	})
	if err != nil {
		return s.failDispatch(ctx, taskID, err)
	}
	return nil
}

func matchesScheduleDelivery(row usecase.ScheduleRecord, delivery usecase.ScheduleDelivery) bool {
	projectID := "schedule:" + row.ScheduleID

	return delivery.ScheduleID == row.ScheduleID &&
		delivery.UserID == row.UserID &&
		delivery.ProjectID == projectID
}

func deliveryScopedID(prefix, deliveryID string) string {
	digest := sha256.Sum256([]byte(deliveryID))

	return prefix + hex.EncodeToString(digest[:16])
}

func (s *Service) failDispatch(ctx context.Context, taskID string, cause error) error {
	if err := s.store.FailScheduleRun(ctx, taskID, cause.Error()); err != nil {
		return fmt.Errorf("record schedule dispatch failure: %w", err)
	}
	return cause
}
