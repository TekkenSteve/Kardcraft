package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	v1stream "task-orchestrator/internal/controller/http/v1/stream"
	"task-orchestrator/internal/repo/persistence"
	"task-orchestrator/internal/usecase"
	ucdto "task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

func TestHandleCreateTaskBoundaries(t *testing.T) {
	t.Run("success", func(t *testing.T) {
		s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("active task conflict", func(t *testing.T) {
		store := newFakeCommandStore()
		store.inserted = false
		store.sessionTasks = []port.SessionTask{{TaskID: "active-1", Status: "running"}}
		s := newCommandTestServer(store, &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusConflict {
			t.Fatalf("expected 409, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("runtime unavailable", func(t *testing.T) {
		s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{runID: "run-1"}, false)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusServiceUnavailable {
			t.Fatalf("expected 503, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("persistence failure", func(t *testing.T) {
		store := newFakeCommandStore()
		store.upsertErr = errors.New("db down")
		s := newCommandTestServer(store, &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusInternalServerError {
			t.Fatalf("expected 500, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("controller does not import runtime dto", func(t *testing.T) {
		data, err := os.ReadFile("handlers/tasks.go")
		if err != nil {
			t.Fatalf("read handlers/tasks.go: %v", err)
		}
		if strings.Contains(string(data), "internal/runtime/temporal/workflows") {
			t.Fatalf("tasks handler leaks runtime DTO import")
		}
	})
}

func TestHandleSessionControlRoutesRemoved(t *testing.T) {
	s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{}, true)
	req := newJSONRequest(http.MethodPost, "/api/v1/sessions/s1/pause", `{"reason":"manual"}`)
	req.Header.Set("Idempotency-Key", "k1")
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rr.Code, rr.Body.String())
	}
}

func TestHandleTaskControlRequiresIdempotencyKey(t *testing.T) {
	store := newFakeCommandStore()
	s := newCommandTestServer(store, &fakeCommandRuntime{}, true)
	req := newJSONRequest(http.MethodPost, "/api/v1/tasks/task-1/pause", `{"reason":"manual"}`)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", rr.Code, rr.Body.String())
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeIdempotencyKeyRequired {
		t.Fatalf("expected %s, got %s", errCodeIdempotencyKeyRequired, payload.Error.Code)
	}
}

func newCommandTestServer(store *fakeCommandStore, runtime *fakeCommandRuntime, temporalEnabled bool) *Server {
	repo := persistence.NewInMemoryTaskRepository()
	publisher := persistence.NewInMemoryEventPublisher()
	taskService := usecase.NewTaskService(repo, publisher, nil)
	commandService := usecase.NewCommandService(taskService, store, runtime)

	enabled := &fakeWorkflowRuntime{enabled: temporalEnabled}
	readModel := usecase.NewReadModelService(&fakeReadModelStore{ready: true})
	s := &Server{
		mux:                http.NewServeMux(),
		taskService:        taskService,
		commandService:     commandService,
		readModel:          readModel,
		workflowSvc:        usecase.NewWorkflowService(enabled, &fakeReadModelStore{ready: true}),
		redisSvc:           &fakeRedisStreamClient{enabled: false},
		timelineByWorkflow: make(map[string][]TimelineEvent),
		uploads:            make(map[string]*uploadState),
		subscribers:        make(map[string]map[int]chan v1stream.OutboundEvent),
		streamReaders:      make(map[string]context.CancelFunc),
		seenStreamIDs:      make(map[string]map[string]struct{}),
	}
	s.registerRoutes()
	return s
}

func newJSONRequest(method, path, body string) *http.Request {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	return req
}

type fakeCommandStore struct {
	upsertErr    error
	inserted     bool
	sessionTasks []port.SessionTask
}

func newFakeCommandStore() *fakeCommandStore {
	return &fakeCommandStore{
		inserted: true,
	}
}

func (f *fakeCommandStore) UpsertSession(ctx context.Context, sessionID, userID, query, status string) error {
	return f.upsertErr
}
func (f *fakeCommandStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	return f.inserted, nil
}
func (f *fakeCommandStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return nil
}
func (f *fakeCommandStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]port.SessionTask, error) {
	return f.sessionTasks, nil
}
func (f *fakeCommandStore) EnsureSessionAccess(ctx context.Context, sessionID, userID string) error {
	return nil
}

type fakeCommandRuntime struct {
	runID     string
	startErr  error
	signalErr error
	cancelErr error
}

func (f *fakeCommandRuntime) StartTaskWorkflow(ctx context.Context, cmd ucdto.CreateTaskCommand) (string, error) {
	if f.startErr != nil {
		return "", f.startErr
	}
	if f.runID == "" {
		return "run-default", nil
	}
	return f.runID, nil
}
func (f *fakeCommandRuntime) SignalWorkflow(ctx context.Context, taskID, signalName string, signal ucdto.ControlSignal) error {
	return f.signalErr
}
func (f *fakeCommandRuntime) CancelWorkflow(ctx context.Context, taskID string) error {
	return f.cancelErr
}

type fakeWorkflowRuntime struct {
	enabled bool
}

func (f *fakeWorkflowRuntime) Enabled() bool { return f.enabled }
func (f *fakeWorkflowRuntime) DescribeWorkflow(ctx context.Context, workflowID, runID string) (*ucdto.WorkflowDescription, error) {
	return nil, errors.New("not implemented")
}
func (f *fakeWorkflowRuntime) GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error) {
	return nil, errors.New("not implemented")
}
func (f *fakeWorkflowRuntime) QueryWorkflowState(ctx context.Context, workflowID string) (*ucdto.WorkflowState, error) {
	return nil, errors.New("not implemented")
}
func (f *fakeWorkflowRuntime) CancelWorkflow(ctx context.Context, workflowID string) error {
	return nil
}
func (f *fakeWorkflowRuntime) ListWorkflowHistory(ctx context.Context, workflowID string) ([]ucdto.WorkflowHistoryEvent, error) {
	return nil, nil
}
func (f *fakeWorkflowRuntime) SignalWorkflow(ctx context.Context, taskID, signalName string, signal ucdto.ControlSignal) error {
	return nil
}

type fakeReadModelStore struct {
	ready bool
}

func (f *fakeReadModelStore) Ready() bool { return f.ready }
func (f *fakeReadModelStore) ListSessions(ctx context.Context, userID string, limit, offset int) ([]ucdto.SessionRow, int, error) {
	return nil, 0, nil
}
func (f *fakeReadModelStore) GetSession(ctx context.Context, sessionID, userID string) (*ucdto.SessionRow, error) {
	return &ucdto.SessionRow{SessionID: sessionID, UserID: userID}, nil
}
func (f *fakeReadModelStore) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	return nil
}
func (f *fakeReadModelStore) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	return 0, nil
}
func (f *fakeReadModelStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]ucdto.TaskRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]ucdto.EventRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]ucdto.EventRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	return map[string]any{}, nil
}
func (f *fakeReadModelStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	return nil
}
func (f *fakeReadModelStore) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	return nil
}
func (f *fakeReadModelStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return "s1", nil
}
func (f *fakeReadModelStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return nil
}
func (f *fakeReadModelStore) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]ucdto.TaskUsageSummary, error) {
	return map[string]ucdto.TaskUsageSummary{}, nil
}
func (f *fakeReadModelStore) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]ucdto.TaskUsageSummary, error) {
	return map[string]ucdto.TaskUsageSummary{}, nil
}
func (f *fakeReadModelStore) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]ucdto.TemplateCatalogRow, int, error) {
	return nil, 0, nil
}
func (f *fakeReadModelStore) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*ucdto.TemplateCatalogRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) GetUserTemplatePreference(ctx context.Context, userID string) (*ucdto.TemplateCatalogRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	return nil
}
func (f *fakeReadModelStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	return nil
}
func (f *fakeReadModelStore) InsertLLMUsage(ctx context.Context, row ucdto.UsageLedgerRow) (bool, error) {
	return true, nil
}

var _ port.ReadModelStore = (*fakeReadModelStore)(nil)
