package v1

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/schedule"
)

func TestScheduleHandlerUpdatesAndRejectsRemovedFields(t *testing.T) {
	service := &fakeScheduleHTTPService{record: usecase.ScheduleRecord{
		ScheduleID: "schedule-1", UserID: "user-1", Name: "Daily review", CronExpression: "0 9 * * *",
		Timezone: "UTC", TaskQuery: "review notes", Status: "active", CreatedAt: time.Date(2026, 7, 12, 0, 0, 0, 0, time.UTC),
	}}
	handler := NewScheduleDetailHandler(scheduleDeps(service))

	request := httptest.NewRequest(http.MethodPut, "/api/v1/schedules/schedule-1", strings.NewReader(`{"name":"Updated review"}`))
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", recorder.Code, recorder.Body.String())
	}
	if service.record.Name != "Updated review" {
		t.Fatalf("expected name update, got %q", service.record.Name)
	}

	request = httptest.NewRequest(http.MethodPost, "/api/v1/schedules", strings.NewReader(`{"name":"Daily","cron_expression":"0 9 * * *","timezone":"UTC","task_query":"review","timeout_seconds":300}`))
	recorder = httptest.NewRecorder()
	NewSchedulesHandler(scheduleDeps(service)).ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected unsupported schedule field to be rejected, got %d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestScheduleRunsResponseUsesRealRunData(t *testing.T) {
	now := time.Date(2026, 7, 12, 8, 0, 0, 0, time.UTC)
	completed := now.Add(2 * time.Minute)
	duration := int64((2 * time.Minute) / time.Millisecond)
	service := &fakeScheduleHTTPService{runs: []usecase.ScheduleRunRow{{
		ScheduleID: "schedule-1", TaskID: "workflow-1", TaskQuery: "review notes", Status: "completed",
		TriggeredAt: now, StartedAt: &now, CompletedAt: &completed, DurationMS: &duration,
		Usage: usecase.TaskUsageSummary{TotalTokens: 42, TotalCostUSD: 0.0125},
	}}}
	recorder := httptest.NewRecorder()
	NewScheduleDetailHandler(scheduleDeps(service)).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/v1/schedules/schedule-1/runs", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Runs []struct {
			WorkflowID string `json:"workflow_id"`
			Query      string `json:"query"`
			Status     string `json:"status"`
			DurationMS int64  `json:"duration_ms"`
		} `json:"runs"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(response.Runs) != 1 || response.Runs[0].WorkflowID != "workflow-1" || response.Runs[0].Query != "review notes" || response.Runs[0].Status != "COMPLETED" || response.Runs[0].DurationMS != duration {
		t.Fatalf("unexpected response: %#v", response)
	}
}

func scheduleDeps(service ScheduleService) SchedulesDeps {
	return SchedulesDeps{
		WriteJSON: writeJSON,
		UserID:    func(*http.Request) string { return "user-1" },
		Service:   service,
	}
}

type fakeScheduleHTTPService struct {
	record usecase.ScheduleRecord
	runs   []usecase.ScheduleRunRow
}

func (s *fakeScheduleHTTPService) Create(_ context.Context, input schedule.CreateInput) (*usecase.ScheduleRecord, error) {
	s.record = usecase.ScheduleRecord{ScheduleID: "schedule-new", UserID: input.UserID, Name: input.Name, Description: input.Description, CronExpression: input.CronExpression, Timezone: input.Timezone, TaskQuery: input.TaskQuery, Status: "active"}
	return &s.record, nil
}
func (s *fakeScheduleHTTPService) Update(_ context.Context, input schedule.UpdateInput) (*usecase.ScheduleRecord, error) {
	if input.Name != nil {
		s.record.Name = *input.Name
	}
	if input.Description != nil {
		s.record.Description = *input.Description
	}
	if input.CronExpression != nil {
		s.record.CronExpression = *input.CronExpression
	}
	if input.Timezone != nil {
		s.record.Timezone = *input.Timezone
	}
	if input.TaskQuery != nil {
		s.record.TaskQuery = *input.TaskQuery
	}
	return &s.record, nil
}
func (s *fakeScheduleHTTPService) Pause(context.Context, string, string, string) (*usecase.ScheduleRecord, error) {
	s.record.Status = "paused"
	return &s.record, nil
}
func (s *fakeScheduleHTTPService) Resume(context.Context, string, string, string) (*usecase.ScheduleRecord, error) {
	s.record.Status = "active"
	return &s.record, nil
}
func (*fakeScheduleHTTPService) Delete(context.Context, string, string) error { return nil }
func (s *fakeScheduleHTTPService) Get(context.Context, string, string) (*usecase.ScheduleRecord, error) {
	return &s.record, nil
}
func (s *fakeScheduleHTTPService) List(context.Context, string, int, int, string) ([]usecase.ScheduleRecord, int, error) {
	return []usecase.ScheduleRecord{s.record}, 1, nil
}
func (s *fakeScheduleHTTPService) Runs(context.Context, string, string, int, int) ([]usecase.ScheduleRunRow, int, error) {
	return s.runs, len(s.runs), nil
}
