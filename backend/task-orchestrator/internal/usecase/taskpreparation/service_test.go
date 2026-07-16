package taskpreparation

import (
	"context"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/readmodel"
	"task-orchestrator/internal/usecase/workspace"
)

func TestPrepareTaskInputBuildsCanonicalRuntimeContext(t *testing.T) {
	payload := `{"attachments":[{"file_id":"file-history","filename":"notes.pdf","mime_type":"application/pdf","size":24}]}`
	store := &preparationStore{
		tasks:  []usecase.TaskRow{{TaskID: "previous", Query: stringPointer("Earlier question"), Result: map[string]any{"message": "Earlier answer"}}},
		events: []usecase.EventRow{{Payload: &payload}},
		workspace: map[string]any{
			"status": "active", "version": int64(2), "cards": []any{map[string]any{"id": "card-1", "title": "Question", "type": "qa"}},
		},
	}
	read := readmodel.New(store)
	workspaces, err := workspace.New(read)
	if err != nil {
		t.Fatalf("workspace.New: %v", err)
	}
	service, err := New(read, workspaces)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	service.now = func() time.Time { return time.Date(2026, 7, 16, 0, 0, 0, 0, time.UTC) }

	prepared, err := service.PrepareTaskInput(context.Background(), usecase.TaskInputPreparationRequest{
		TaskID: "task-1", TaskType: usecase.TaskTypeMain, UserID: "user-1", SessionID: "session-1", CorrelationID: "request-1",
		Input:       usecase.AgentTaskInput{Query: "Current question", ContextEnvelope: map[string]any{"ext_hint": "ignored"}},
		Attachments: []usecase.FileAttachment{{FileID: "file-current", Filename: "current.txt", MimeType: "text/plain", Size: 12}},
	})
	if err != nil {
		t.Fatalf("PrepareTaskInput: %v", err)
	}
	if got, want := prepared.EffectiveFileIDs, []string{"file-current", "file-history"}; !sameStrings(got, want) {
		t.Fatalf("effective file ids = %#v, want %#v", got, want)
	}
	if len(prepared.Input.ConversationHistory) != 2 || prepared.Input.ConversationHistory[0].Content != "Earlier question" || prepared.Input.ConversationHistory[1].Content != "Earlier answer" {
		t.Fatalf("unexpected session history: %#v", prepared.Input.ConversationHistory)
	}
	if _, exists := prepared.Input.ContextEnvelope["ext_hint"]; exists {
		t.Fatalf("client extension leaked into execution envelope: %#v", prepared.Input.ContextEnvelope)
	}
	if got := prepared.Input.ContextEnvelope["correlation_id"]; got != "request-1" {
		t.Fatalf("correlation_id = %#v, want request-1", got)
	}
	artifacts := prepared.Input.ContextEnvelope["artifacts"].(map[string]any)
	if files, ok := artifacts["files"].([]map[string]any); !ok || len(files) != 1 || files[0]["file_id"] != "file-history" {
		t.Fatalf("unexpected inherited artifacts: %#v", artifacts["files"])
	}
	if len(prepared.SessionEvents) != 5 {
		t.Fatalf("session events = %d, want planner, lifecycle, and attachment records", len(prepared.SessionEvents))
	}
	if prepared.SessionEvents[0].Type != "PLANNER_TRACE" || prepared.SessionEvents[3].Type != "WORKSPACE_LIFECYCLE_EVALUATED" || prepared.SessionEvents[4].Type != "MESSAGE_SENT" {
		t.Fatalf("unexpected prepared event types: %#v", prepared.SessionEvents)
	}
}

type preparationStore struct {
	usecase.ReadModelStore
	tasks     []usecase.TaskRow
	events    []usecase.EventRow
	workspace map[string]any
}

func (s *preparationStore) Ready() bool { return true }
func (s *preparationStore) ListSessionTasks(context.Context, string, string) ([]usecase.TaskRow, error) {
	return s.tasks, nil
}
func (s *preparationStore) ListSessionEvents(context.Context, string, int, int) ([]usecase.EventRow, error) {
	return s.events, nil
}
func (s *preparationStore) LoadWorkspace(context.Context, string) (map[string]any, error) {
	return s.workspace, nil
}

func stringPointer(value string) *string { return &value }

func sameStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
