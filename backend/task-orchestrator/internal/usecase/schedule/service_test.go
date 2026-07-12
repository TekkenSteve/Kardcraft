package schedule

import (
	"context"
	"errors"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
)

func TestDispatchCreatesOneScheduledTaskWithDefaultTemplate(t *testing.T) {
	store := &fakeScheduleStore{record: usecase.ScheduleRecord{
		ScheduleID: "schedule-1", UserID: "user-1", Status: "active", TaskQuery: "summarize today's notes",
	}}
	command := &fakeCommand{}
	service := New(store, &fakeRuntime{}, command, fakeReadModel{template: &usecase.TemplateCatalogRow{
		DefaultTemplateID: "template-1", DefaultTemplateVersion: 3,
	}})
	service.now = func() time.Time { return time.Date(2026, 7, 12, 8, 0, 0, 0, time.UTC) }

	delivery := scheduleDelivery(store.record, "delivery-1")
	if err := service.Dispatch(context.Background(), delivery); err != nil {
		t.Fatalf("Dispatch() error = %v", err)
	}
	if len(store.runs) != 1 {
		t.Fatalf("expected one run record, got %d", len(store.runs))
	}
	if len(command.created) != 1 {
		t.Fatalf("expected one task command, got %d", len(command.created))
	}
	created := command.created[0]
	if created.TaskID != store.runs[0].TaskID || created.SessionID != store.runs[0].SessionID {
		t.Fatalf("task and schedule run must share IDs: command=%#v run=%#v", created, store.runs[0])
	}
	if created.Input.Context.TemplateID != "template-1" || created.Input.Context.TemplateVersion != 3 {
		t.Fatalf("expected resolved default template, got %#v", created.Input.Context)
	}
	if created.Metadata.Source != "schedule" {
		t.Fatalf("expected schedule source, got %q", created.Metadata.Source)
	}
}

func TestDispatchRecordsFailureWhenDefaultTemplateIsUnavailable(t *testing.T) {
	store := &fakeScheduleStore{record: usecase.ScheduleRecord{
		ScheduleID: "schedule-1", UserID: "user-1", Status: "active", TaskQuery: "summarize today's notes",
	}}
	command := &fakeCommand{}
	service := New(store, &fakeRuntime{}, command, fakeReadModel{err: errors.New("no template")})

	err := service.Dispatch(context.Background(), scheduleDelivery(store.record, "delivery-1"))
	if err == nil {
		t.Fatal("expected dispatch failure")
	}
	if len(store.runs) != 1 || store.failedTaskID != store.runs[0].TaskID {
		t.Fatalf("expected failure recorded for created schedule run, runs=%#v failed=%q", store.runs, store.failedTaskID)
	}
	if len(command.created) != 0 {
		t.Fatalf("task must not start without a default template, got %#v", command.created)
	}
}

func TestDispatchReusesDeliveryScopedTaskOnRetry(t *testing.T) {
	store := &fakeScheduleStore{record: usecase.ScheduleRecord{
		ScheduleID: "schedule-1", UserID: "user-1", Status: "active", TaskQuery: "summarize today's notes",
	}}
	command := &fakeCommand{}
	service := New(store, &fakeRuntime{}, command, fakeReadModel{template: &usecase.TemplateCatalogRow{
		DefaultTemplateID: "template-1", DefaultTemplateVersion: 3,
	}})
	delivery := scheduleDelivery(store.record, "delivery-1")

	if err := service.Dispatch(context.Background(), delivery); err != nil {
		t.Fatalf("first Dispatch() error = %v", err)
	}
	if err := service.Dispatch(context.Background(), delivery); err != nil {
		t.Fatalf("retry Dispatch() error = %v", err)
	}
	if len(store.runs) != 1 {
		t.Fatalf("expected one durable run record, got %d", len(store.runs))
	}
	if len(command.created) != 2 {
		t.Fatalf("expected delivery retry to reissue the idempotent start request, got %d calls", len(command.created))
	}
	if command.created[0].TaskID != command.created[1].TaskID || command.created[0].SessionID != command.created[1].SessionID {
		t.Fatalf("delivery retry must reuse task and session IDs: %#v", command.created)
	}
	if command.created[0].Metadata.RequestID != delivery.DeliveryID {
		t.Fatalf("expected delivery ID as request idempotency key, got %q", command.created[0].Metadata.RequestID)
	}
}

func TestReconcileAppliesEveryScheduleDeclaration(t *testing.T) {
	store := &fakeScheduleStore{record: usecase.ScheduleRecord{
		ScheduleID: "schedule-1", UserID: "user-1", Status: "active", TaskQuery: "summarize today's notes",
	}}
	runtime := &fakeRuntime{}
	service := New(store, runtime, nil, nil)

	if err := service.Reconcile(context.Background()); err != nil {
		t.Fatalf("Reconcile() error = %v", err)
	}
	if len(runtime.created) != 1 || runtime.created[0].ScheduleID != store.record.ScheduleID {
		t.Fatalf("expected schedule declaration to be applied, got %#v", runtime.created)
	}
}

type fakeScheduleStore struct {
	record       usecase.ScheduleRecord
	runs         []usecase.ScheduleRunRow
	deliveryRuns map[string]usecase.ScheduleRunRow
	failedTaskID string
}

func (s *fakeScheduleStore) CreateSchedule(_ context.Context, row usecase.ScheduleRecord) error {
	s.record = row
	return nil
}
func (s *fakeScheduleStore) GetSchedule(_ context.Context, _, _ string) (*usecase.ScheduleRecord, error) {
	return &s.record, nil
}
func (s *fakeScheduleStore) GetScheduleByID(_ context.Context, _ string) (*usecase.ScheduleRecord, error) {
	return &s.record, nil
}
func (s *fakeScheduleStore) ListAllSchedules(context.Context) ([]usecase.ScheduleRecord, error) {
	return []usecase.ScheduleRecord{s.record}, nil
}
func (s *fakeScheduleStore) ListSchedules(context.Context, string, int, int, string) ([]usecase.ScheduleRecord, int, error) {
	return []usecase.ScheduleRecord{s.record}, 1, nil
}
func (s *fakeScheduleStore) UpdateSchedule(_ context.Context, row usecase.ScheduleRecord) error {
	s.record = row
	return nil
}
func (s *fakeScheduleStore) UpdateScheduleStatus(_ context.Context, _ string, status string) error {
	s.record.Status = status
	return nil
}
func (s *fakeScheduleStore) DeleteSchedule(context.Context, string, string) (int64, error) {
	return 1, nil
}
func (s *fakeScheduleStore) CreateScheduleRun(_ context.Context, row usecase.ScheduleRunRow) (bool, error) {
	if s.deliveryRuns == nil {
		s.deliveryRuns = make(map[string]usecase.ScheduleRunRow)
	}
	if _, exists := s.deliveryRuns[row.DeliveryID]; exists {
		return false, nil
	}
	s.deliveryRuns[row.DeliveryID] = row
	s.runs = append(s.runs, row)
	return true, nil
}
func (s *fakeScheduleStore) FailScheduleRun(_ context.Context, taskID, _ string) error {
	s.failedTaskID = taskID
	return nil
}
func (s *fakeScheduleStore) ListScheduleRuns(context.Context, string, string, int, int) ([]usecase.ScheduleRunRow, int, error) {
	return s.runs, len(s.runs), nil
}

type fakeRuntime struct{ created []usecase.ScheduleRecord }

func (r *fakeRuntime) Create(_ context.Context, row usecase.ScheduleRecord) error {
	r.created = append(r.created, row)
	return nil
}
func (*fakeRuntime) Update(context.Context, usecase.ScheduleRecord) error         { return nil }
func (*fakeRuntime) Pause(context.Context, usecase.ScheduleRecord, string) error  { return nil }
func (*fakeRuntime) Resume(context.Context, usecase.ScheduleRecord, string) error { return nil }
func (*fakeRuntime) Delete(context.Context, usecase.ScheduleRecord) error         { return nil }

type fakeCommand struct{ created []usecase.CreateTaskCommand }

func (c *fakeCommand) CreateTaskInSession(_ context.Context, command usecase.CreateTaskCommand) (*usecase.CreateTaskResult, string, error) {
	c.created = append(c.created, command)
	return &usecase.CreateTaskResult{WorkflowID: command.TaskID, SessionID: command.SessionID}, "", nil
}
func (*fakeCommand) SendMessageToSession(context.Context, usecase.SessionMessageCommand) (*usecase.SessionMessageResult, error) {
	return nil, nil
}
func (*fakeCommand) ControlSession(context.Context, usecase.SessionControlCommand) (*usecase.SessionControlResult, error) {
	return nil, nil
}

type fakeReadModel struct {
	template *usecase.TemplateCatalogRow
	err      error
}

func (m fakeReadModel) GetResolvedDefaultTemplate(context.Context, string) (*usecase.TemplateCatalogRow, error) {
	return m.template, m.err
}
func (fakeReadModel) GetTaskUsageSummaryMapByTaskIDs(context.Context, string, []string) (map[string]usecase.TaskUsageSummary, error) {
	return map[string]usecase.TaskUsageSummary{}, nil
}

func scheduleDelivery(row usecase.ScheduleRecord, deliveryID string) usecase.ScheduleDelivery {
	projectID := "schedule:" + row.ScheduleID

	return usecase.ScheduleDelivery{
		DeliveryID:  deliveryID,
		ScheduleID:  row.ScheduleID,
		UserID:      row.UserID,
		ProjectID:   projectID,
		TriggeredAt: time.Date(2026, 7, 12, 8, 0, 0, 0, time.UTC),
	}
}
