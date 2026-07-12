package v1

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"task-orchestrator/internal/controller/restapi/middleware"
	"task-orchestrator/internal/entity"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/outcomeprojector"
	"task-orchestrator/internal/usecase/schedule"
)

const maxTimelineEventsInMemory = 500

type SessionLifecycleStore interface {
	outcomeprojector.Store
	Ready() bool
	StartLifecycle(ctx context.Context)
	Close()
}

type TimelineEvent struct {
	ID         int64  `json:"id"`
	Type       string `json:"type"`
	Message    string `json:"message,omitempty"`
	Timestamp  string `json:"timestamp,omitempty"`
	WorkflowID string `json:"workflow_id,omitempty"`
	RunID      string `json:"run_id,omitempty"`
	SessionID  string `json:"session_id,omitempty"`
	Seq        int64  `json:"seq,omitempty"`
	TaskID     string `json:"task_id,omitempty"`
	StreamID   string `json:"stream_id,omitempty"`
	Payload    any    `json:"payload,omitempty"`
}

type Server struct {
	port           int
	httpServer     *http.Server
	mux            *http.ServeMux
	httpClient     *http.Client
	ankiRuntimeURL string
	bgCancel       context.CancelFunc
	closeFuncs     []func()
	agentRuntime   usecase.AgentRuntime

	taskService     usecase.Task
	commandService  usecase.Command
	readModel       usecase.ReadModel
	sessionStore    SessionLifecycleStore
	defaultModelRef string
	scheduleService *schedule.Service

	mu                 sync.RWMutex
	timelineByWorkflow map[string][]TimelineEvent

	subscribers             map[string]map[int]chan OutboundEvent
	streamReaders           map[string]context.CancelFunc
	subscriberSeq           int
	eventSeq                int64
	duplicateDrops          int64
	seenStreamIDs           map[string]map[string]struct{}
	runSeqByRunID           map[string]int64
	workflowRunByWorkflowID map[string]string
	invalidRuntimeEvents    int64
	llmUsageIngested        int64
	llmUsageDeduped         int64
	llmUsageFailed          int64
	llmUsageInvalid         int64
}

type ServerDependencies struct {
	HTTPClient     *http.Client
	AnkiRuntimeURL string

	TaskService     usecase.Task
	CommandService  usecase.Command
	ReadModel       usecase.ReadModel
	SessionStore    SessionLifecycleStore
	DefaultModelRef string
	AgentRuntime    usecase.AgentRuntime
	ScheduleService *schedule.Service

	CloseFuncs []func()
}

func NewServer(port int, deps ServerDependencies) *Server {
	if port == 0 {
		port = 50050
	}
	httpClient := deps.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 5 * time.Second}
	}
	ankiRuntimeURL := strings.TrimSpace(deps.AnkiRuntimeURL)
	if ankiRuntimeURL == "" {
		ankiRuntimeURL = "http://anki-runtime:8012"
	}
	s := &Server{
		port:                    port,
		mux:                     http.NewServeMux(),
		httpClient:              httpClient,
		ankiRuntimeURL:          ankiRuntimeURL,
		closeFuncs:              deps.CloseFuncs,
		agentRuntime:            deps.AgentRuntime,
		taskService:             deps.TaskService,
		commandService:          deps.CommandService,
		readModel:               deps.ReadModel,
		sessionStore:            deps.SessionStore,
		defaultModelRef:         strings.TrimSpace(deps.DefaultModelRef),
		scheduleService:         deps.ScheduleService,
		timelineByWorkflow:      make(map[string][]TimelineEvent),
		subscribers:             make(map[string]map[int]chan OutboundEvent),
		streamReaders:           make(map[string]context.CancelFunc),
		seenStreamIDs:           make(map[string]map[string]struct{}),
		runSeqByRunID:           make(map[string]int64),
		workflowRunByWorkflowID: make(map[string]string),
	}

	s.registerRoutes()
	return s
}

func (s *Server) Handler() http.Handler {
	return middleware.Chain(
		middleware.Recover(),
		middleware.RequestID(),
		middleware.AccessLog(),
		s.withAuth,
	)(s.mux)
}

func (s *Server) Addr() string {
	return fmt.Sprintf(":%d", s.port)
}

func (s *Server) Start(ctx context.Context) error {
	if s.sessionStore != nil && s.sessionStore.Ready() {
		bgCtx, cancel := context.WithCancel(context.Background())
		s.bgCancel = cancel
		s.sessionStore.StartLifecycle(bgCtx)
	}
	s.httpServer = &http.Server{
		Addr:         s.Addr(),
		Handler:      s.Handler(),
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 0,
		IdleTimeout:  60 * time.Second,
	}
	go func() {
		if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("orchestrator server error: %v", err)
		}
	}()
	return nil
}

func (s *Server) Shutdown(ctx context.Context) error {
	if s.bgCancel != nil {
		s.bgCancel()
	}
	if s.sessionStore != nil {
		s.sessionStore.Close()
	}
	for i := len(s.closeFuncs) - 1; i >= 0; i-- {
		if s.closeFuncs[i] != nil {
			s.closeFuncs[i]()
		}
	}
	if s.httpServer == nil {
		return nil
	}
	return s.httpServer.Shutdown(ctx)
}

func (s *Server) registerRoutes() {
	s.registerTaskRoutes()
	s.registerSessionAndTemplateRoutes()
	s.registerMiscRoutes()
}

func (s *Server) nextEventID() int64 {
	return atomic.AddInt64(&s.eventSeq, 1)
}

func (s *Server) nextWorkflowID(taskType string) string {
	name := strings.TrimSpace(taskType)
	if name == "" {
		name = "main"
	}
	return fmt.Sprintf("workflow_%s_%d", name, time.Now().UTC().UnixNano())
}

func (s *Server) isAgentRuntimeAvailable() bool {
	return s.agentRuntime != nil
}

func (s *Server) authorizeTaskAccess(ctx context.Context, userID string, taskID string) bool {
	return AuthorizeTaskAccess(ctx, s.readModel, userID, taskID)
}

func (s *Server) ProjectDomainEvents(events []entity.DomainEvent) {
	ProjectDomainEvents(events, DomainProjectionDeps{
		TaskService:                s.taskService,
		ReadModel:                  s.readModel,
		EnsureWorkflowStreamReader: s.ensureWorkflowStreamReader,
		StopWorkflowStreamReader:   s.stopWorkflowStreamReader,
		AppendTimeline:             s.appendTimeline,
	})
}

type contextKey string

const userIDContextKey contextKey = "user_id"

var errAuthMissingGatewayIdentity = errors.New("missing trusted identity header")

func (s *Server) withAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions || !requiresAuthPath(r.URL.Path) {
			next.ServeHTTP(w, r)
			return
		}
		// Keep route-handler tests focused on business logic by honoring
		// explicitly injected user IDs in request context.
		if injected := strings.TrimSpace(userIDFromContext(r.Context())); injected != "" {
			next.ServeHTTP(w, r)
			return
		}
		userID, err := s.authenticateRequest(r)
		if err != nil {
			writeAPIError(w, http.StatusUnauthorized, errCodeUnauthenticated, "authentication required", map[string]any{"provider": "gateway"})
			return
		}
		ctx := context.WithValue(r.Context(), userIDContextKey, userID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func requiresAuthPath(path string) bool {
	return path == "/api" || strings.HasPrefix(path, "/api/")
}

func (s *Server) authenticateRequest(r *http.Request) (string, error) {
	userID := strings.TrimSpace(r.Header.Get("X-User-Id"))
	if userID == "" {
		return "", errAuthMissingGatewayIdentity
	}
	return userID, nil
}

func userIDFromContext(ctx context.Context) string {
	v, _ := ctx.Value(userIDContextKey).(string)
	return strings.TrimSpace(v)
}
