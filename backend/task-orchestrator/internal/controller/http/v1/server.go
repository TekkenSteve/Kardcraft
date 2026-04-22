package httpserver

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

	v1middleware "task-orchestrator/internal/controller/http/v1/middleware"
	v1stream "task-orchestrator/internal/controller/http/v1/stream"
	v1support "task-orchestrator/internal/controller/http/v1/support"
	"task-orchestrator/internal/entity/task"
	"task-orchestrator/internal/usecase"
)

const maxTimelineEventsInMemory = 500

type redisStreamClient interface {
	Enabled() bool
	StreamRead(ctx context.Context, workflowID, fromID string, count int64, block time.Duration) ([]v1stream.Entry, string, error)
	GetCheckpoint(ctx context.Context, workflowID string) (string, error)
	SetCheckpoint(ctx context.Context, workflowID, streamID string) error
	Stats() map[string]any
}

type sessionLifecycleStore interface {
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
	TaskID     string `json:"task_id,omitempty"`
	StreamID   string `json:"stream_id,omitempty"`
	Payload    any    `json:"payload,omitempty"`
}

type ScheduleInfo struct {
	ScheduleID        string         `json:"schedule_id"`
	Name              string         `json:"name"`
	Description       string         `json:"description,omitempty"`
	CronExpression    string         `json:"cron_expression"`
	Timezone          string         `json:"timezone"`
	TaskQuery         string         `json:"task_query"`
	TaskContext       map[string]any `json:"task_context,omitempty"`
	Status            string         `json:"status"`
	NextRunAt         string         `json:"next_run_at,omitempty"`
	LastRunAt         string         `json:"last_run_at,omitempty"`
	TotalRuns         int            `json:"total_runs"`
	SuccessfulRuns    int            `json:"successful_runs"`
	FailedRuns        int            `json:"failed_runs"`
	MaxBudgetPerRunUS float64        `json:"max_budget_per_run_usd,omitempty"`
	TimeoutSeconds    int            `json:"timeout_seconds,omitempty"`
	CreatedAt         string         `json:"created_at"`
}

type ScheduleRun struct {
	WorkflowID   string  `json:"workflow_id"`
	Query        string  `json:"query"`
	Status       string  `json:"status"`
	Result       string  `json:"result,omitempty"`
	ErrorMessage string  `json:"error_message,omitempty"`
	ModelUsed    string  `json:"model_used,omitempty"`
	Provider     string  `json:"provider,omitempty"`
	TotalTokens  int     `json:"total_tokens"`
	TotalCostUSD float64 `json:"total_cost_usd"`
	DurationMS   int64   `json:"duration_ms,omitempty"`
	TriggeredAt  string  `json:"triggered_at"`
	StartedAt    string  `json:"started_at,omitempty"`
	CompletedAt  string  `json:"completed_at,omitempty"`
}

type uploadState struct {
	UploadID    string `json:"upload_id"`
	Status      string `json:"status"`
	FileName    string `json:"file_name"`
	Chunks      int    `json:"chunks"`
	Received    int    `json:"received"`
	SessionID   string `json:"session_id,omitempty"`
	CreatedAt   string `json:"created_at"`
	CompletedAt string `json:"completed_at,omitempty"`
}

type Server struct {
	port           int
	httpServer     *http.Server
	mux            *http.ServeMux
	httpClient     *http.Client
	ankiRuntimeURL string
	bgCancel       context.CancelFunc
	closeFuncs     []func()
	redisSvc       redisStreamClient

	taskService    *usecase.TaskService
	commandService *usecase.CommandService
	readModel      *usecase.ReadModelService
	workflowSvc    *usecase.WorkflowService
	sessionStore   sessionLifecycleStore

	mu                 sync.RWMutex
	timelineByWorkflow map[string][]TimelineEvent
	uploads            map[string]*uploadState

	subscribers            map[string]map[int]chan v1stream.OutboundEvent
	streamReaders          map[string]context.CancelFunc
	subscriberSeq          int
	eventSeq               int64
	duplicateDrops         int64
	seenStreamIDs          map[string]map[string]struct{}
	llmUsageIngested       int64
	llmUsageDeduped        int64
	llmUsageFailed         int64
	llmUsageInvalid        int64
}

type ServerDependencies struct {
	HTTPClient     *http.Client
	AnkiRuntimeURL string

	TaskService    *usecase.TaskService
	CommandService *usecase.CommandService
	ReadModel      *usecase.ReadModelService
	WorkflowSvc    *usecase.WorkflowService
	SessionStore   sessionLifecycleStore
	RedisSvc       redisStreamClient

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
		port:               port,
		mux:                http.NewServeMux(),
		httpClient:         httpClient,
		ankiRuntimeURL:     ankiRuntimeURL,
		closeFuncs:         deps.CloseFuncs,
		redisSvc:           deps.RedisSvc,
		taskService:        deps.TaskService,
		commandService:     deps.CommandService,
		readModel:          deps.ReadModel,
		workflowSvc:        deps.WorkflowSvc,
		sessionStore:       deps.SessionStore,
		timelineByWorkflow: make(map[string][]TimelineEvent),
		uploads:            make(map[string]*uploadState),
		subscribers:        make(map[string]map[int]chan v1stream.OutboundEvent),
		streamReaders:      make(map[string]context.CancelFunc),
		seenStreamIDs:      make(map[string]map[string]struct{}),
	}

	s.registerRoutes()
	return s
}

func (s *Server) Handler() http.Handler {
	return v1middleware.Chain(
		v1middleware.Recover(),
		v1middleware.RequestID(),
		v1middleware.AccessLog(),
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
	s.registerWorkflowRoutes()
	s.registerUploadRoutes()
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

func (s *Server) isTemporalEnabled() bool {
	return s.workflowSvc != nil && s.workflowSvc.Enabled()
}

func (s *Server) authorizeTaskAccess(ctx context.Context, userID string, taskID string) bool {
	return v1support.AuthorizeTaskAccess(ctx, s.readModel, userID, taskID)
}

func (s *Server) ProjectDomainEvents(events []task.DomainEvent) {
	v1support.ProjectDomainEvents(events, v1support.DomainProjectionDeps{
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
