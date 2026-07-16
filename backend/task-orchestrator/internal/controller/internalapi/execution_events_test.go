package internalapi

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
)

func TestExecutionEventsHandlerWritesOnlyThroughExecutionPort(t *testing.T) {
	execution := &recordingExecution{}
	handler := NewExecutionEventsHandler(ExecutionEventsDeps{
		Validator: acceptToken{},
		Execution: execution,
	})
	req := httptest.NewRequest(http.MethodPost, "/internal/execution/runs/run-1/events", strings.NewReader(`{"event_id":"source-1","run_id":"run-1","sequence":1,"event_type":"run.completed","source":"langgraph","timestamp":"2026-07-15T00:00:00Z","payload":{"result":"ok"}}`))
	req.Header.Set("Authorization", "Bearer service-token")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusAccepted {
		t.Fatalf("status = %d, body=%s", rr.Code, rr.Body.String())
	}
	if execution.event.RunID != "run-1" || execution.event.Sequence != 1 {
		t.Fatalf("event = %#v", execution.event)
	}
}

func TestExecutionEventsHandlerRejectsMissingServiceToken(t *testing.T) {
	handler := NewExecutionEventsHandler(ExecutionEventsDeps{Validator: acceptToken{}, Execution: &recordingExecution{}})
	req := httptest.NewRequest(http.MethodPost, "/internal/execution/runs/run-1/events", strings.NewReader(`{}`))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusUnauthorized)
	}
}

func TestExecutionEventsHandlerRejectsRunScopeMismatch(t *testing.T) {
	execution := &recordingExecution{}
	handler := NewExecutionEventsHandler(ExecutionEventsDeps{Validator: acceptToken{}, Execution: execution})
	req := httptest.NewRequest(http.MethodPost, "/internal/execution/runs/run-1/events", strings.NewReader(`{"event_id":"source-1","run_id":"run-2","sequence":1,"event_type":"run.completed","source":"langgraph","timestamp":"2026-07-15T00:00:00Z"}`))
	req.Header.Set("Authorization", "Bearer service-token")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusBadRequest)
	}
	if execution.event.RunID != "" {
		t.Fatalf("execution should not receive invalid scope: %#v", execution.event)
	}
}

func TestExecutionEventsHandlerPropagatesExecutionScopeRejection(t *testing.T) {
	execution := &recordingExecution{err: errors.New("unknown execution route")}
	handler := NewExecutionEventsHandler(ExecutionEventsDeps{Validator: acceptToken{}, Execution: execution})
	req := httptest.NewRequest(http.MethodPost, "/internal/execution/runs/run-1/events", strings.NewReader(`{"event_id":"source-1","run_id":"run-1","sequence":1,"event_type":"run.completed","source":"langgraph","timestamp":"2026-07-15T00:00:00Z"}`))
	req.Header.Set("Authorization", "Bearer service-token")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusBadRequest)
	}
}

type acceptToken struct{}

func (acceptToken) Validate(_ context.Context, token string) error {
	if token != "service-token" {
		return errRejectedToken{}
	}
	return nil
}

type errRejectedToken struct{}

func (errRejectedToken) Error() string { return "rejected" }

type recordingExecution struct {
	event usecase.ExternalTaskExecutionEvent
	err   error
}

func (r *recordingExecution) StartTaskExecution(context.Context, usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (r *recordingExecution) GetTaskExecutionStatus(context.Context, string) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (r *recordingExecution) SignalTaskExecution(context.Context, string, usecase.TaskExecutionSignal) error {
	return nil
}
func (r *recordingExecution) ControlTaskExecution(context.Context, string, usecase.TaskExecutionControl) error {
	return nil
}
func (r *recordingExecution) SubscribeTaskExecution(context.Context, usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	return nil, nil
}
func (r *recordingExecution) IngestTaskExecutionEvent(_ context.Context, event usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	r.event = event
	if r.err != nil {
		return usecase.TaskExecutionEvent{}, r.err
	}
	return usecase.TaskExecutionEvent{EventID: "stored-1", Sequence: 4, Timestamp: time.Now()}, nil
}
