package workflows

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

type fakeOutcomeStore struct {
	updateErr    error
	insertErr    error
	saveErr      error
	sessionID    string
	workspace    map[string]any
	calls        []string
	lastStreamID string
	streamIDs    []string
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

func TestPersistTaskOutcomeActivity_CriticalFinalStateFailure(t *testing.T) {
	store := &fakeOutcomeStore{sessionID: "s1", updateErr: errors.New("db down")}
	prev := persistenceStore
	persistenceStore = store
	t.Cleanup(func() { persistenceStore = prev })

	err := PersistTaskOutcomeActivity(context.Background(), PersistTaskOutcomeInput{
		TaskID:     "t1",
		WorkflowID: "w1",
		Status:     "completed",
		Result: map[string]any{
			"schema_version": "task-outcome",
			"task_id":        "t1",
			"workflow_id":    "w1",
			"status":         "completed",
			"session_id":     "s1",
			"user_id":        "u1",
			"message":        "ok",
			"final_cards":    []any{},
		},
		CompletedAt: time.Now().UTC(),
	})
	if err == nil {
		t.Fatalf("expected error when UpdateTaskFinalState fails")
	}
	if len(store.calls) == 0 || store.calls[0] != "update" {
		t.Fatalf("expected update first, got calls=%v", store.calls)
	}
}

func TestPersistTaskOutcomeActivity_NonCriticalProjectionFailuresDontRollback(t *testing.T) {
	store := &fakeOutcomeStore{
		sessionID: "s1",
		insertErr: errors.New("insert failed"),
		saveErr:   errors.New("save failed"),
	}
	prev := persistenceStore
	persistenceStore = store
	t.Cleanup(func() { persistenceStore = prev })

	err := PersistTaskOutcomeActivity(context.Background(), PersistTaskOutcomeInput{
		TaskID:     "t1",
		WorkflowID: "w1",
		Status:     "completed",
		Result: map[string]any{
			"schema_version": "task-outcome",
			"task_id":        "t1",
			"workflow_id":    "w1",
			"status":         "completed",
			"session_id":     "s1",
			"user_id":        "u1",
			"message":        "ok",
			"final_cards": []any{
				map[string]any{"id": "c1", "front": "f", "back": "b", "model": "mcq"},
			},
		},
		CompletedAt: time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("expected nil error on projection failures, got %v", err)
	}
	if len(store.calls) < 4 {
		t.Fatalf("expected update/get_session/insert_event/save_workspace calls, got %v", store.calls)
	}
	if !containsStreamID(store.streamIDs, "terminal:t1:completed") {
		t.Fatalf("expected terminal stream id in %v", store.streamIDs)
	}
}

func TestPersistTaskOutcomeActivity_FailedStatusUsesFallbackOutcome(t *testing.T) {
	store := &fakeOutcomeStore{sessionID: "s1"}
	prev := persistenceStore
	persistenceStore = store
	t.Cleanup(func() { persistenceStore = prev })

	err := PersistTaskOutcomeActivity(context.Background(), PersistTaskOutcomeInput{
		TaskID:      "t-failed",
		WorkflowID:  "w-failed",
		Status:      "failed",
		Result:      map[string]any{"bad": "shape"},
		Error:       "worker failed",
		CompletedAt: time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("failed status should tolerate decode failure, got %v", err)
	}
	if store.lastStreamID != "terminal:t-failed:failed" {
		t.Fatalf("unexpected terminal stream id: %q", store.lastStreamID)
	}
}

func containsStreamID(values []string, expected string) bool {
	for _, value := range values {
		if strings.TrimSpace(value) == expected {
			return true
		}
	}
	return false
}
