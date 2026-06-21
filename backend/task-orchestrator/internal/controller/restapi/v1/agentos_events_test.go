package v1

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestAgentOSEventsHandlerAppendsProgressEvent(t *testing.T) {
	readStore := &fakeReadModelStore{ready: true}
	var appended struct {
		workflowID string
		sessionID  string
		eventType  string
		message    string
		streamID   string
		persist    bool
	}
	handler := NewAgentOSEventsHandler(AgentOSEventsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		ReadModel:     readStore,
		AppendTimeline: func(workflowID, sessionID, eventType, message, streamID string, payload any, persist bool) {
			appended.workflowID = workflowID
			appended.sessionID = sessionID
			appended.eventType = eventType
			appended.message = message
			appended.streamID = streamID
			appended.persist = persist
		},
	})
	req := newJSONRequest(http.MethodPost, "/api/v1/agentos/runs/run-1/events", `{
		"event_id":"evt-1",
		"run_id":"run-1",
		"thread_id":"s1",
		"event_type":"WORKFLOW_WAITING_INPUT",
		"source":"kardcraft.agent_workflow",
		"payload":{"message":"Need input","correlation_id":"corr-1"}
	}`)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rr.Code, rr.Body.String())
	}
	if appended.workflowID != "run-1" || appended.sessionID != "s1" {
		t.Fatalf("unexpected timeline target: %#v", appended)
	}
	if appended.eventType != "WORKFLOW_WAITING_INPUT" || appended.message != "Need input" {
		t.Fatalf("unexpected event projection: %#v", appended)
	}
	if appended.streamID != "agentos:evt-1" {
		t.Fatalf("expected agentos stream id, got %q", appended.streamID)
	}
	if !appended.persist {
		t.Fatalf("progress events must persist timeline entries")
	}
	if len(readStore.statusUpdates) != 1 || readStore.statusUpdates[0].status != "running" {
		t.Fatalf("expected waiting input to keep task running, got %#v", readStore.statusUpdates)
	}
}

func TestAgentOSEventsHandlerProjectsTerminalOutcome(t *testing.T) {
	store := &fakeAgentOSOutcomeStore{sessionID: "s1"}
	var appended struct {
		eventType string
		persist   bool
	}
	handler := NewAgentOSEventsHandler(AgentOSEventsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		ReadModel:     &fakeReadModelStore{ready: true},
		OutcomeStore:  store,
		AppendTimeline: func(workflowID, sessionID, eventType, message, streamID string, payload any, persist bool) {
			appended.eventType = eventType
			appended.persist = persist
		},
	})
	req := newJSONRequest(http.MethodPost, "/api/v1/agentos/runs/run-terminal/events", `{
		"event_id":"evt-terminal",
		"run_id":"run-terminal",
		"thread_id":"s1",
		"event_type":"WORKFLOW_COMPLETED",
		"source":"kardcraft.agent_workflow",
		"payload":{
			"message":"Done",
			"correlation_id":"corr-terminal",
			"task_outcome":{
				"schema_version":"task-outcome",
				"task_id":"run-terminal",
				"workflow_id":"run-terminal",
				"session_id":"s1",
				"user_id":"u1",
				"status":"completed",
				"message":"Done",
				"final_cards":[]
			}
		}
	}`)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rr.Code, rr.Body.String())
	}
	if store.updatedTaskID != "run-terminal" || store.updatedStatus != "completed" {
		t.Fatalf("expected terminal update, got task=%q status=%q", store.updatedTaskID, store.updatedStatus)
	}
	if !containsString(store.eventTypes, "WORKFLOW_COMPLETED") {
		t.Fatalf("expected terminal event insert, got %v", store.eventTypes)
	}
	if appended.eventType != "WORKFLOW_COMPLETED" || appended.persist {
		t.Fatalf("terminal timeline append should be transient, got %#v", appended)
	}
}

func TestAgentOSEventsHandlerMapsStandardAgentOSEvents(t *testing.T) {
	store := &fakeAgentOSOutcomeStore{sessionID: "s1"}
	var appended struct {
		eventType string
		persist   bool
	}
	handler := NewAgentOSEventsHandler(AgentOSEventsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		ReadModel:     &fakeReadModelStore{ready: true},
		OutcomeStore:  store,
		AppendTimeline: func(workflowID, sessionID, eventType, message, streamID string, payload any, persist bool) {
			appended.eventType = eventType
			appended.persist = persist
		},
	})
	req := newJSONRequest(http.MethodPost, "/api/v1/agentos/runs/run-standard/events", `{
		"event_id":"evt-standard",
		"run_id":"run-standard",
		"thread_id":"s1",
		"event_type":"run.completed",
		"source":"kardcraft.agent_workflow",
		"payload":{
			"message":"Done",
			"correlation_id":"corr-standard",
			"task_outcome":{
				"schema_version":"task-outcome",
				"task_id":"run-standard",
				"workflow_id":"run-standard",
				"session_id":"s1",
				"user_id":"u1",
				"status":"completed",
				"message":"Done",
				"final_cards":[]
			}
		}
	}`)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rr.Code, rr.Body.String())
	}
	if store.updatedStatus != "completed" {
		t.Fatalf("expected completed projection, got %q", store.updatedStatus)
	}
	if !containsString(store.eventTypes, "WORKFLOW_COMPLETED") {
		t.Fatalf("expected mapped terminal event insert, got %v", store.eventTypes)
	}
	if appended.eventType != "WORKFLOW_COMPLETED" || appended.persist {
		t.Fatalf("terminal timeline append should use mapped event and stay transient, got %#v", appended)
	}
}

func TestAgentOSEventsHandlerRejectsMismatchedRunID(t *testing.T) {
	handler := NewAgentOSEventsHandler(AgentOSEventsDeps{
		WriteJSON:      writeJSON,
		WriteAPIError:  writeAPIError,
		AppendTimeline: func(string, string, string, string, string, any, bool) {},
	})
	req := newJSONRequest(http.MethodPost, "/api/v1/agentos/runs/run-path/events", `{
		"run_id":"run-body",
		"event_type":"WORKFLOW_PROGRESS",
		"payload":{"correlation_id":"corr-1"}
	}`)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", rr.Code, rr.Body.String())
	}
	if !strings.Contains(rr.Body.String(), "run_id in path and body must match") {
		t.Fatalf("expected run_id mismatch error, got %s", rr.Body.String())
	}
}

type fakeAgentOSOutcomeStore struct {
	sessionID     string
	updatedTaskID string
	updatedStatus string
	eventTypes    []string
	workspace     map[string]any
}

func (f *fakeAgentOSOutcomeStore) UpdateTaskFinalState(ctx context.Context, taskID string, status string, result any, errMsg string, completedAt time.Time) error {
	f.updatedTaskID = taskID
	f.updatedStatus = status
	return nil
}

func (f *fakeAgentOSOutcomeStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return f.sessionID, nil
}

func (f *fakeAgentOSOutcomeStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	f.eventTypes = append(f.eventTypes, eventType)
	return nil
}

func (f *fakeAgentOSOutcomeStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	if f.workspace == nil {
		return map[string]any{"session_id": sessionID, "version": 0}, nil
	}
	return f.workspace, nil
}

func (f *fakeAgentOSOutcomeStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	f.workspace = workspace
	return nil
}

func containsString(values []string, expected string) bool {
	for _, value := range values {
		if value == expected {
			return true
		}
	}
	return false
}
