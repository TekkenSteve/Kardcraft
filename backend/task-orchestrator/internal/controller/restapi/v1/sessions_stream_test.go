package v1

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"task-orchestrator/internal/usecase"
)

func TestSessionStreamStateUsesAuthenticatedTenantScope(t *testing.T) {
	conversation := &fakeConversationAPI{snapshot: usecase.ConversationThreadSnapshot{ThreadID: "thread-1", Cursor: 17}}
	deps := conversationTestDeps(conversation, nil)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions/thread-1/stream-state", nil)
	rr := httptest.NewRecorder()

	NewSessionsRouter(deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
	if conversation.snapshotScope.ThreadID != "thread-1" || conversation.snapshotScope.AccountID != "account-1" || conversation.snapshotScope.ProjectID != "thread-1" {
		t.Fatalf("unexpected tenant scope: %#v", conversation.snapshotScope)
	}
}

func TestSessionStreamStateRejectsConversationTenantMismatch(t *testing.T) {
	conversation := &fakeConversationAPI{snapshotErr: usecase.ErrConversationTenantMismatch}
	deps := conversationTestDeps(conversation, nil)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions/thread-1/stream-state", nil)
	rr := httptest.NewRecorder()

	NewSessionsRouter(deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rr.Code, rr.Body.String())
	}
}

func TestSessionEventsUsesLastEventIDAndQueryTakesPrecedence(t *testing.T) {
	tests := []struct {
		name, target, lastEventID string
		want                      int64
	}{
		{name: "header", target: "/api/v1/sessions/thread-1/events", lastEventID: "41", want: 41},
		{name: "query", target: "/api/v1/sessions/thread-1/events?after=42", lastEventID: "41", want: 42},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			conversation := &fakeConversationAPI{}
			deps := conversationTestDeps(conversation, nil)
			req := httptest.NewRequest(http.MethodGet, tc.target, nil)
			req.Header.Set("Last-Event-ID", tc.lastEventID)
			rr := httptest.NewRecorder()

			NewSessionsRouter(deps).ServeHTTP(rr, req)
			if rr.Code != http.StatusOK {
				t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
			}
			if conversation.streamScope.AfterSequence != tc.want {
				t.Fatalf("expected cursor %d, got %#v", tc.want, conversation.streamScope)
			}
		})
	}
}

func TestSessionEventsRejectsMalformedCursor(t *testing.T) {
	conversation := &fakeConversationAPI{}
	deps := conversationTestDeps(conversation, nil)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions/thread-1/events?after=not-a-sequence", nil)
	rr := httptest.NewRecorder()

	NewSessionsRouter(deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", rr.Code, rr.Body.String())
	}
	if conversation.subscribed {
		t.Fatal("malformed cursor must be rejected before subscription")
	}
}

func TestSessionRunMapsInterruptValidationToConflict(t *testing.T) {
	for _, conflict := range []error{usecase.ErrConversationInterruptRequired, usecase.ErrConversationInterruptMismatch} {
		t.Run(conflict.Error(), func(t *testing.T) {
			command := &fakeConversationCommand{sendErr: conflict}
			deps := conversationTestDeps(&fakeConversationAPI{}, command)
			req := httptest.NewRequest(http.MethodPost, "/api/v1/sessions/thread-1/runs", strings.NewReader(`{"content":"continue","interrupt_id":"interrupt-1"}`))
			req.Header.Set("Idempotency-Key", "message-1")
			rr := httptest.NewRecorder()

			NewSessionsRouter(deps).ServeHTTP(rr, req)
			if rr.Code != http.StatusConflict {
				t.Fatalf("expected 409, got %d body=%s", rr.Code, rr.Body.String())
			}
		})
	}
}

func TestSessionRunPassesServerInterruptAndIdempotencyKey(t *testing.T) {
	command := &fakeConversationCommand{result: &usecase.SessionMessageResult{
		SessionID: "thread-1", RunID: "run-2", ProcessID: "process-1", Cursor: 23,
	}}
	deps := conversationTestDeps(&fakeConversationAPI{}, command)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sessions/thread-1/runs", strings.NewReader(`{"content":"continue","interrupt_id":"interrupt-1"}`))
	req.Header.Set("Idempotency-Key", "message-1")
	rr := httptest.NewRecorder()

	NewSessionsRouter(deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rr.Code, rr.Body.String())
	}
	if !strings.Contains(rr.Body.String(), `"run_id":"run-2"`) || !strings.Contains(rr.Body.String(), `"process_id":"process-1"`) || !strings.Contains(rr.Body.String(), `"cursor":23`) {
		t.Fatalf("expected snake_case run response, got body=%s", rr.Body.String())
	}
	if command.sent.InterruptID != "interrupt-1" || command.sent.IdempotencyKey != "message-1" || command.sent.UserID != "account-1" {
		t.Fatalf("unexpected continuation command: %#v", command.sent)
	}
}

func conversationTestDeps(conversation usecase.Conversation, command usecase.Command) SessionsDeps {
	return SessionsDeps{
		WriteJSON:      writeJSON,
		UserID:         func(*http.Request) string { return "account-1" },
		ReadModel:      &fakeReadModelStore{ready: true},
		Conversation:   conversation,
		CommandService: command,
	}
}

type fakeConversationAPI struct {
	snapshot      usecase.ConversationThreadSnapshot
	snapshotErr   error
	snapshotScope usecase.ConversationThreadScope
	streamScope   usecase.ConversationStreamScope
	subscribed    bool
}

func (*fakeConversationAPI) StartRun(context.Context, usecase.ConversationStartRequest) (usecase.ConversationRun, error) {
	return usecase.ConversationRun{}, nil
}
func (*fakeConversationAPI) IngestEvent(context.Context, usecase.ExternalConversationEvent) (usecase.ConversationEvent, error) {
	return usecase.ConversationEvent{}, nil
}
func (f *fakeConversationAPI) GetThreadSnapshot(_ context.Context, scope usecase.ConversationThreadScope) (usecase.ConversationThreadSnapshot, error) {
	f.snapshotScope = scope
	return f.snapshot, f.snapshotErr
}
func (f *fakeConversationAPI) SubscribeThread(_ context.Context, scope usecase.ConversationStreamScope) (usecase.ConversationSubscription, error) {
	f.subscribed = true
	f.streamScope = scope
	events := make(chan usecase.ConversationEvent)
	close(events)
	return &fakeConversationSubscription{events: events}, nil
}

type fakeConversationSubscription struct {
	events <-chan usecase.ConversationEvent
}

func (f *fakeConversationSubscription) Events() <-chan usecase.ConversationEvent { return f.events }
func (*fakeConversationSubscription) Close() error                               { return nil }

type fakeConversationCommand struct {
	result  *usecase.SessionMessageResult
	sendErr error
	sent    usecase.SessionMessageCommand
}

func (*fakeConversationCommand) CreateTaskInSession(context.Context, usecase.CreateTaskCommand) (*usecase.CreateTaskResult, string, error) {
	return nil, "", errors.New("not implemented")
}
func (f *fakeConversationCommand) SendMessageToSession(_ context.Context, command usecase.SessionMessageCommand) (*usecase.SessionMessageResult, error) {
	f.sent = command
	return f.result, f.sendErr
}
func (*fakeConversationCommand) ControlSession(context.Context, usecase.SessionControlCommand) (*usecase.SessionControlResult, error) {
	return nil, errors.New("not implemented")
}
func (*fakeConversationCommand) RecordSessionEvents(context.Context, []usecase.SessionEvent) error {
	return errors.New("not implemented")
}
