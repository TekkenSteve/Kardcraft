package command

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"task-orchestrator/internal/usecase"
)

func TestDispatchPendingConversationsMarksSuccessfulDispatchDone(t *testing.T) {
	outbox := &fakeConversationOutbox{claimed: []usecase.ConversationDispatch{newStartDispatch(t, 1)}}
	execution := &fakeDispatchExecution{}
	service := &UseCase{execution: execution, outbox: outbox, now: fixedDispatchTime}

	if err := service.DispatchPendingConversations(context.Background(), 10); err != nil {
		t.Fatalf("dispatch pending conversations: %v", err)
	}
	if execution.starts != 1 {
		t.Fatalf("expected one workflow start, got %d", execution.starts)
	}
	if outbox.done != "dispatch-1" {
		t.Fatalf("expected dispatch to be marked done, got %q", outbox.done)
	}
}

func TestDispatchPendingConversationsPreservesResumeActor(t *testing.T) {
	payload, err := json.Marshal(conversationDispatchPayload{
		SignalTaskID: "process-1",
		Signal: &usecase.TaskExecutionSignal{
			Type: usecase.AgentSignalUserMessage, IdempotencyKey: "message-1", ActorID: "account-1",
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	outbox := &fakeConversationOutbox{claimed: []usecase.ConversationDispatch{{
		DispatchID: "dispatch-1", Kind: "resume", Payload: payload,
	}}}
	execution := &fakeDispatchExecution{}
	service := &UseCase{execution: execution, outbox: outbox, now: fixedDispatchTime}

	if err := service.DispatchPendingConversations(context.Background(), 10); err != nil {
		t.Fatalf("dispatch pending conversations: %v", err)
	}
	if execution.signal == nil || execution.signal.ActorID != "account-1" {
		t.Fatalf("expected resume actor to survive outbox dispatch, got %#v", execution.signal)
	}
}

func TestDispatchPendingConversationsRetriesTransientFailure(t *testing.T) {
	outbox := &fakeConversationOutbox{claimed: []usecase.ConversationDispatch{newStartDispatch(t, 2)}}
	execution := &fakeDispatchExecution{startErr: errors.New("temporal unavailable")}
	service := &UseCase{execution: execution, outbox: outbox, now: fixedDispatchTime}

	if err := service.DispatchPendingConversations(context.Background(), 10); err != nil {
		t.Fatalf("dispatch pending conversations: %v", err)
	}
	if outbox.retryID != "dispatch-1" || outbox.retryError != "temporal unavailable" {
		t.Fatalf("expected retry state, got id=%q error=%q", outbox.retryID, outbox.retryError)
	}
	want := fixedDispatchTime().Add(2 * time.Second)
	if !outbox.retryAt.Equal(want) {
		t.Fatalf("expected exponential retry at %s, got %s", want, outbox.retryAt)
	}
}

func TestDispatchPendingConversationsPersistsRunErrorAtAttemptLimit(t *testing.T) {
	item := newStartDispatch(t, maxConversationDispatchAttempts)
	outbox := &fakeConversationOutbox{claimed: []usecase.ConversationDispatch{item}}
	execution := &fakeDispatchExecution{startErr: errors.New("permanent failure")}
	conversation := &fakeDispatchConversation{snapshot: usecase.ConversationThreadSnapshot{
		Runs: []usecase.ConversationRun{{RunID: item.RunID, Status: "pending"}},
	}}
	store := &fakeDispatchStore{}
	service := &UseCase{
		store: store, execution: execution, conversation: conversation, outbox: outbox, now: fixedDispatchTime,
	}

	if err := service.DispatchPendingConversations(context.Background(), 10); err != nil {
		t.Fatalf("dispatch pending conversations: %v", err)
	}
	if conversation.ingested == nil || conversation.ingested.EventType != usecase.ConversationEventRunError {
		t.Fatalf("expected RUN_ERROR, got %#v", conversation.ingested)
	}
	if conversation.ingested.ThreadID != item.ThreadID || conversation.ingested.RunID != item.RunID {
		t.Fatalf("terminal event has wrong scope: %#v", conversation.ingested)
	}
	if outbox.failed != item.DispatchID {
		t.Fatalf("expected failed outbox row, got %q", outbox.failed)
	}
	if store.status != "failed" || store.taskID != item.ProcessID {
		t.Fatalf("expected failed business projection, got task=%q status=%q", store.taskID, store.status)
	}
}

func TestDispatchPendingConversationsAcceptsAmbiguousDeliveryWhenRunStarted(t *testing.T) {
	item := newStartDispatch(t, maxConversationDispatchAttempts)
	outbox := &fakeConversationOutbox{claimed: []usecase.ConversationDispatch{item}}
	execution := &fakeDispatchExecution{startErr: errors.New("deadline exceeded")}
	conversation := &fakeDispatchConversation{snapshot: usecase.ConversationThreadSnapshot{
		Runs: []usecase.ConversationRun{{RunID: item.RunID, Status: "running"}},
	}}
	service := &UseCase{execution: execution, conversation: conversation, outbox: outbox, now: fixedDispatchTime}

	if err := service.DispatchPendingConversations(context.Background(), 10); err != nil {
		t.Fatalf("dispatch pending conversations: %v", err)
	}
	if outbox.done != item.DispatchID || outbox.failed != "" {
		t.Fatalf("expected ambiguous delivery to be acknowledged, got done=%q failed=%q", outbox.done, outbox.failed)
	}
	if conversation.ingested != nil {
		t.Fatalf("must not emit RUN_ERROR for an already started run: %#v", conversation.ingested)
	}
}

func newStartDispatch(t *testing.T, attempts int) usecase.ConversationDispatch {
	t.Helper()
	payload := conversationDispatchPayload{Start: &usecase.TaskExecutionRequest{RunID: "process-1"}}
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	return usecase.ConversationDispatch{
		DispatchID: "dispatch-1", ThreadID: "thread-1", RunID: "run-1", ProcessID: "process-1",
		AccountID: "account-1", ProjectID: "thread-1", Kind: "start", Payload: encoded, Attempts: attempts,
	}
}

func fixedDispatchTime() time.Time { return time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC) }

type fakeConversationOutbox struct {
	claimed               []usecase.ConversationDispatch
	done, retryID, failed string
	retryError            string
	retryAt               time.Time
}

func (f *fakeConversationOutbox) EnqueueConversationDispatch(context.Context, usecase.ConversationDispatch) error {
	return nil
}
func (f *fakeConversationOutbox) ClaimConversationDispatches(context.Context, int, time.Duration) ([]usecase.ConversationDispatch, error) {
	return f.claimed, nil
}
func (f *fakeConversationOutbox) MarkConversationDispatchDone(_ context.Context, id string) error {
	f.done = id
	return nil
}
func (f *fakeConversationOutbox) RetryConversationDispatch(_ context.Context, id, message string, at time.Time) error {
	f.retryID, f.retryError, f.retryAt = id, message, at
	return nil
}
func (f *fakeConversationOutbox) FailConversationDispatch(_ context.Context, id, _ string) error {
	f.failed = id
	return nil
}

type fakeDispatchExecution struct {
	starts   int
	startErr error
	signal   *usecase.TaskExecutionSignal
}

func (f *fakeDispatchExecution) StartTaskExecution(context.Context, usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	f.starts++
	return usecase.TaskExecutionStatus{}, f.startErr
}
func (*fakeDispatchExecution) GetTaskExecutionStatus(context.Context, string) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (f *fakeDispatchExecution) SignalTaskExecution(_ context.Context, _ string, signal usecase.TaskExecutionSignal) error {
	f.signal = &signal
	return nil
}
func (*fakeDispatchExecution) ControlTaskExecution(context.Context, string, usecase.TaskExecutionControl) error {
	return nil
}
func (*fakeDispatchExecution) SubscribeTaskExecution(context.Context, usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	return nil, nil
}
func (*fakeDispatchExecution) IngestTaskExecutionEvent(context.Context, usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	return usecase.TaskExecutionEvent{}, nil
}

type fakeDispatchConversation struct {
	ingested *usecase.ExternalConversationEvent
	snapshot usecase.ConversationThreadSnapshot
}

func (*fakeDispatchConversation) StartRun(context.Context, usecase.ConversationStartRequest) (usecase.ConversationRun, error) {
	return usecase.ConversationRun{}, nil
}
func (f *fakeDispatchConversation) IngestEvent(_ context.Context, event usecase.ExternalConversationEvent) (usecase.ConversationEvent, error) {
	f.ingested = &event
	return usecase.ConversationEvent{}, nil
}
func (f *fakeDispatchConversation) GetThreadSnapshot(context.Context, usecase.ConversationThreadScope) (usecase.ConversationThreadSnapshot, error) {
	return f.snapshot, nil
}
func (*fakeDispatchConversation) SubscribeThread(context.Context, usecase.ConversationStreamScope) (usecase.ConversationSubscription, error) {
	return nil, nil
}

type fakeDispatchStore struct{ taskID, status string }

func (*fakeDispatchStore) UpsertSession(context.Context, string, string, string, string) error {
	return nil
}
func (*fakeDispatchStore) InsertTaskIfNoActive(context.Context, string, string, string, string, string, string) (bool, error) {
	return true, nil
}
func (*fakeDispatchStore) ListSessionTasks(context.Context, string, string) ([]usecase.SessionTask, error) {
	return nil, nil
}
func (f *fakeDispatchStore) UpdateTaskStatus(_ context.Context, taskID, status, _ string) error {
	f.taskID, f.status = taskID, status
	return nil
}
func (*fakeDispatchStore) EnsureSessionAccess(context.Context, string, string) error { return nil }
