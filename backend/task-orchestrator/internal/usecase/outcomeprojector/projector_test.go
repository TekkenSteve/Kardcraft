package outcomeprojector

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

type fakeOutcomeStore struct {
	updateErr      error
	insertErr      error
	saveErr        error
	outboxErr      error
	sessionID      string
	workspace      map[string]any
	calls          []string
	lastStreamID   string
	streamIDs      []string
	eventTypes     []string
	payloads       []string
}

func (f *fakeOutcomeStore) UpdateTaskFinalState(ctx context.Context, taskID string, status string, result any, errMsg string, completedAt time.Time) error {
	f.calls = append(f.calls, "update")
	return f.updateErr
}

func (f *fakeOutcomeStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	f.calls = append(f.calls, "get_session")
	return f.sessionID, nil
}

func (f *fakeOutcomeStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	f.calls = append(f.calls, "insert_event")
	f.lastStreamID = streamID
	f.streamIDs = append(f.streamIDs, streamID)
	f.eventTypes = append(f.eventTypes, eventType)
	f.payloads = append(f.payloads, payload)
	return f.insertErr
}

func (f *fakeOutcomeStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	f.calls = append(f.calls, "load_workspace")
	if f.workspace == nil {
		return map[string]any{
			"session_id": sessionID,
			"version":    0,
		}, nil
	}
	return f.workspace, nil
}

func (f *fakeOutcomeStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	f.calls = append(f.calls, "save_workspace")
	f.workspace = workspace
	return f.saveErr
}

func persistInput(status string, finalCards []any) Input {
	return Input{
		TaskID:        "t1",
		WorkflowID:    "w1",
		RunID:         "run1",
		CorrelationID: "corr1",
		Status:        status,
		Result: map[string]any{
			"schema_version": "task-outcome",
			"task_id":        "t1",
			"workflow_id":    "w1",
			"status":         status,
			"session_id":     "s1",
			"user_id":        "u1",
			"message":        "ok",
			"final_cards":    finalCards,
		},
		CompletedAt: time.Now().UTC(),
	}
}

func TestProject_CriticalFinalStateFailure(t *testing.T) {
	store := &fakeOutcomeStore{sessionID: "s1", updateErr: errors.New("db down")}

	err := New(store).Project(context.Background(), persistInput("completed", []any{}))
	if err == nil {
		t.Fatalf("expected error when UpdateTaskFinalState fails")
	}
	if len(store.calls) == 0 || store.calls[0] != "update" {
		t.Fatalf("expected update first, got calls=%v", store.calls)
	}
}

func TestProject_WorkspaceSaveFailureBlocksTerminal(t *testing.T) {
	store := &fakeOutcomeStore{
		sessionID: "s1",
		saveErr:   errors.New("save failed"),
	}

	err := New(store).Project(context.Background(), persistInput("completed", []any{
		map[string]any{"id": "c1", "front": "f", "back": "b", "model": "mcq"},
	}))
	if err == nil {
		t.Fatalf("expected workspace save error")
	}
	if containsStreamID(store.streamIDs, "terminal:t1:completed") {
		t.Fatalf("terminal must not publish after workspace save failure, streamIDs=%v", store.streamIDs)
	}
}

func TestProject_WorkspaceEventPrecedesTerminalAndCarriesCards(t *testing.T) {
	store := &fakeOutcomeStore{sessionID: "s1"}

	projection, err := New(store).ProjectWithEvents(context.Background(), persistInput("completed", []any{
		map[string]any{"id": "c1", "front": "f", "back": "b", "model": "mcq"},
	}))
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}

	workspaceIndex := indexOf(store.eventTypes, "WORKSPACE_UPDATED")
	terminalIndex := indexOf(store.streamIDs, "terminal:t1:completed")
	if workspaceIndex < 0 {
		t.Fatalf("expected WORKSPACE_UPDATED event in %v", store.eventTypes)
	}
	if terminalIndex < 0 {
		t.Fatalf("expected terminal event in %v", store.streamIDs)
	}
	if workspaceIndex >= terminalIndex {
		t.Fatalf("expected WORKSPACE_UPDATED before terminal, eventTypes=%v streamIDs=%v", store.eventTypes, store.streamIDs)
	}
	if projection == nil || len(projection.Events) != 2 {
		t.Fatalf("expected two projected events, got %#v", projection)
	}
	if projection.Events[0].EventType != "WORKSPACE_UPDATED" || projection.Events[1].EventType != "WORKFLOW_COMPLETED" {
		t.Fatalf("expected projected workspace before terminal, got %#v", projection.Events)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(store.payloads[workspaceIndex]), &payload); err != nil {
		t.Fatalf("workspace payload should be valid json: %v", err)
	}
	cards, ok := payload["cards"].([]any)
	if !ok || len(cards) != 1 {
		t.Fatalf("expected workspace payload cards, got %#v", payload["cards"])
	}
}

func TestProject_FailedStatusUsesFallbackOutcome(t *testing.T) {
	store := &fakeOutcomeStore{sessionID: "s1"}

	err := New(store).Project(context.Background(), Input{
		TaskID:        "t-failed",
		WorkflowID:    "w-failed",
		RunID:         "run-failed",
		CorrelationID: "corr-failed",
		Status:        "failed",
		Result:        map[string]any{"bad": "shape"},
		Error:         "worker failed",
		CompletedAt:   time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("failed status should tolerate decode failure, got %v", err)
	}
	if store.lastStreamID != "terminal:t-failed:failed" {
		t.Fatalf("unexpected terminal stream id: %q", store.lastStreamID)
	}
}

func containsStreamID(values []string, expected string) bool {
	return indexOf(values, expected) >= 0
}

func indexOf(values []string, expected string) int {
	for index, value := range values {
		if strings.TrimSpace(value) == expected {
			return index
		}
	}
	return -1
}
