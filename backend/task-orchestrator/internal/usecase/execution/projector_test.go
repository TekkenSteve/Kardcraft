package execution

import (
	"context"
	"sync"
	"testing"
	"time"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
)

func TestProjectorReplayKeepsOneReadModelEvent(t *testing.T) {
	store := newProjectionStore()
	projector := newTestProjector(t, store)
	event := usecase.TaskExecutionEvent{
		EventID: "agentos-event-1", EventType: "run.started", RunID: "run-1", Sequence: 1,
		Timestamp: time.Date(2026, 7, 16, 0, 0, 0, 0, time.UTC), Payload: map[string]any{"message": "started"},
	}
	for range 2 {
		if err := projector.Project(context.Background(), "task-1", event); err != nil {
			t.Fatalf("Project: %v", err)
		}
	}
	if store.status != "running" {
		t.Fatalf("status = %q, want running", store.status)
	}
	if count := store.eventCount(); count != 1 {
		t.Fatalf("persisted event count = %d, want one durable stream event", count)
	}
}

func TestProjectorReplayKeepsOneTerminalResult(t *testing.T) {
	store := newProjectionStore()
	projector := newTestProjector(t, store)
	event := usecase.TaskExecutionEvent{
		EventID: "agentos-event-terminal", EventType: "run.completed", RunID: "run-1", Sequence: 2,
		Timestamp: time.Date(2026, 7, 16, 0, 0, 1, 0, time.UTC), Payload: map[string]any{
			"schema_version": "task-outcome", "task_id": "task-1", "workflow_id": "task-1", "status": "completed",
			"session_id": "session-1", "user_id": "user-1", "message": "done", "correlation_id": "request-1",
		},
	}
	for range 2 {
		if err := projector.Project(context.Background(), "task-1", event); err != nil {
			t.Fatalf("Project: %v", err)
		}
	}
	if store.finalStatus != "completed" {
		t.Fatalf("final status = %q, want completed", store.finalStatus)
	}
	if count := store.eventCount(); count != 1 {
		t.Fatalf("persisted terminal count = %d, want one", count)
	}
}

func TestProjectorReconcileStartsOneSubscriberPerActiveTask(t *testing.T) {
	execution := &subscribingExecution{started: make(chan struct{}, 2)}
	routes := staticRoutes{routes: []repo.TaskExecutionRoute{{TaskID: "task-1", PlanID: "plan-1", AccountID: "user-1", ProjectID: "session-1", NodeID: "langgraph", BackendRunID: "run-1"}}}
	projector, err := NewProjector(execution, routes, newProjectionStore())
	if err != nil {
		t.Fatalf("NewProjector: %v", err)
	}
	defer projector.Close()
	if err := projector.Reconcile(context.Background()); err != nil {
		t.Fatalf("first Reconcile: %v", err)
	}
	if err := projector.Reconcile(context.Background()); err != nil {
		t.Fatalf("second Reconcile: %v", err)
	}
	select {
	case <-execution.started:
	case <-time.After(time.Second):
		t.Fatal("projector did not subscribe to active execution")
	}
	select {
	case <-execution.started:
		t.Fatal("projector opened a duplicate subscriber")
	case <-time.After(50 * time.Millisecond):
	}
}

func TestProjectorCloseStopsActiveSubscription(t *testing.T) {
	execution := &subscribingExecution{started: make(chan struct{}, 1), closed: make(chan struct{}, 1)}
	projector, err := NewProjector(execution, noopRoutes{}, newProjectionStore())
	if err != nil {
		t.Fatalf("NewProjector: %v", err)
	}
	projector.Start("task-1")
	select {
	case <-execution.started:
	case <-time.After(time.Second):
		t.Fatal("projector did not subscribe")
	}
	projector.Close()
	select {
	case <-execution.closed:
	case <-time.After(time.Second):
		t.Fatal("projector did not close the active subscription")
	}
}

func TestProjectorReadsSubscriptionChannelOnce(t *testing.T) {
	subscription := &countingSubscription{events: make(chan usecase.TaskExecutionEvent, 2)}
	subscription.events <- usecase.TaskExecutionEvent{
		EventID: "event-1", EventType: "run.started", RunID: "run-1", ThreadID: "session-1", Sequence: 1,
		Timestamp: time.Date(2026, 7, 25, 0, 0, 0, 0, time.UTC), Payload: map[string]any{"message": "started"},
	}
	subscription.events <- usecase.TaskExecutionEvent{
		EventID: "event-2", EventType: "WORKFLOW_WAITING_INPUT", RunID: "run-1", ThreadID: "session-1", Sequence: 2,
		Timestamp: time.Date(2026, 7, 25, 0, 0, 1, 0, time.UTC), Payload: map[string]any{"message": "question"},
	}
	close(subscription.events)
	execution := &singleSubscriptionExecution{subscription: subscription}
	store := newProjectionStore()
	projector, err := NewProjector(execution, noopRoutes{}, store)
	if err != nil {
		t.Fatalf("NewProjector: %v", err)
	}
	projector.consume(context.Background(), "task-1")
	if subscription.eventsCalls != 1 {
		t.Fatalf("Events calls = %d, want 1", subscription.eventsCalls)
	}
	if count := store.eventCount(); count != 2 {
		t.Fatalf("persisted event count = %d, want 2", count)
	}
}

func newTestProjector(t *testing.T, store *projectionStore) *Projector {
	t.Helper()
	projector, err := NewProjector(noopExecution{}, noopRoutes{}, store)
	if err != nil {
		t.Fatalf("NewProjector: %v", err)
	}
	return projector
}

type projectionStore struct {
	mu          sync.Mutex
	status      string
	finalStatus string
	events      map[string]struct{}
}

func newProjectionStore() *projectionStore {
	return &projectionStore{events: make(map[string]struct{})}
}

func (s *projectionStore) GetTaskSession(context.Context, string) (string, error) {
	return "session-1", nil
}
func (s *projectionStore) UpdateTaskStatus(_ context.Context, _ string, status, _ string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status = status
	return nil
}
func (s *projectionStore) UpdateTaskFinalState(_ context.Context, _ string, status string, _ any, _ string, _ time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.finalStatus = status
	return nil
}
func (s *projectionStore) InsertEvent(_ context.Context, _, _, workflowID, eventType, _ string, _, streamID string, _ time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.events[workflowID+":"+eventType+":"+streamID] = struct{}{}
	return nil
}
func (s *projectionStore) LoadWorkspace(context.Context, string) (map[string]any, error) {
	return map[string]any{"version": 0}, nil
}
func (s *projectionStore) SaveWorkspace(context.Context, string, map[string]any) error { return nil }
func (s *projectionStore) eventCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.events)
}

type noopExecution struct{}

func (noopExecution) StartTaskExecution(context.Context, usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (noopExecution) GetTaskExecutionStatus(context.Context, string) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (noopExecution) SignalTaskExecution(context.Context, string, usecase.TaskExecutionSignal) error {
	return nil
}
func (noopExecution) ControlTaskExecution(context.Context, string, usecase.TaskExecutionControl) error {
	return nil
}
func (noopExecution) SubscribeTaskExecution(context.Context, usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	return nil, nil
}
func (noopExecution) IngestTaskExecutionEvent(context.Context, usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	return usecase.TaskExecutionEvent{}, nil
}

type singleSubscriptionExecution struct {
	subscription usecase.TaskExecutionSubscription
}

func (s *singleSubscriptionExecution) StartTaskExecution(context.Context, usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (s *singleSubscriptionExecution) GetTaskExecutionStatus(context.Context, string) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (s *singleSubscriptionExecution) SignalTaskExecution(context.Context, string, usecase.TaskExecutionSignal) error {
	return nil
}
func (s *singleSubscriptionExecution) ControlTaskExecution(context.Context, string, usecase.TaskExecutionControl) error {
	return nil
}
func (s *singleSubscriptionExecution) SubscribeTaskExecution(context.Context, usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	return s.subscription, nil
}
func (s *singleSubscriptionExecution) IngestTaskExecutionEvent(context.Context, usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	return usecase.TaskExecutionEvent{}, nil
}

type countingSubscription struct {
	events      chan usecase.TaskExecutionEvent
	eventsCalls int
}

func (s *countingSubscription) Events() <-chan usecase.TaskExecutionEvent {
	s.eventsCalls++
	return s.events
}
func (*countingSubscription) Close() error { return nil }

type noopRoutes struct{}

func (noopRoutes) BindTaskExecutionRoute(context.Context, repo.TaskExecutionRoute) error { return nil }
func (noopRoutes) GetTaskExecutionRoute(context.Context, string) (repo.TaskExecutionRoute, bool, error) {
	return repo.TaskExecutionRoute{}, false, nil
}
func (noopRoutes) GetTaskExecutionRouteByBackendRun(context.Context, string) (repo.TaskExecutionRoute, bool, error) {
	return repo.TaskExecutionRoute{}, false, nil
}
func (noopRoutes) ListActiveTaskExecutionRoutes(context.Context) ([]repo.TaskExecutionRoute, error) {
	return nil, nil
}

type staticRoutes struct{ routes []repo.TaskExecutionRoute }

func (s staticRoutes) BindTaskExecutionRoute(context.Context, repo.TaskExecutionRoute) error {
	return nil
}
func (s staticRoutes) GetTaskExecutionRoute(context.Context, string) (repo.TaskExecutionRoute, bool, error) {
	return repo.TaskExecutionRoute{}, false, nil
}
func (s staticRoutes) GetTaskExecutionRouteByBackendRun(context.Context, string) (repo.TaskExecutionRoute, bool, error) {
	return repo.TaskExecutionRoute{}, false, nil
}
func (s staticRoutes) ListActiveTaskExecutionRoutes(context.Context) ([]repo.TaskExecutionRoute, error) {
	return s.routes, nil
}

type subscribingExecution struct {
	started chan struct{}
	closed  chan struct{}
}

func (s *subscribingExecution) StartTaskExecution(context.Context, usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (s *subscribingExecution) GetTaskExecutionStatus(context.Context, string) (usecase.TaskExecutionStatus, error) {
	return usecase.TaskExecutionStatus{}, nil
}
func (s *subscribingExecution) SignalTaskExecution(context.Context, string, usecase.TaskExecutionSignal) error {
	return nil
}
func (s *subscribingExecution) ControlTaskExecution(context.Context, string, usecase.TaskExecutionControl) error {
	return nil
}
func (s *subscribingExecution) SubscribeTaskExecution(_ context.Context, _ usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	s.started <- struct{}{}
	return &blockingSubscription{events: make(chan usecase.TaskExecutionEvent), closed: s.closed}, nil
}
func (s *subscribingExecution) IngestTaskExecutionEvent(context.Context, usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	return usecase.TaskExecutionEvent{}, nil
}

type blockingSubscription struct {
	events chan usecase.TaskExecutionEvent
	closed chan struct{}
	once   sync.Once
}

func (s *blockingSubscription) Events() <-chan usecase.TaskExecutionEvent { return s.events }
func (s *blockingSubscription) Close() error {
	s.once.Do(func() {
		close(s.events)
		if s.closed != nil {
			s.closed <- struct{}{}
		}
	})
	return nil
}
