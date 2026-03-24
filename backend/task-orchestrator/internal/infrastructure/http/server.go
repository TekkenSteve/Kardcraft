package httpserver

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
	tclient "go.temporal.io/sdk/client"

	"task-orchestrator/internal/application"
	"task-orchestrator/internal/infrastructure/persistence"
	redissvc "task-orchestrator/internal/infrastructure/redis"
)

const maxTimelineEventsInMemory = 500

type redisStreamClient interface {
	Enabled() bool
	StreamRead(ctx context.Context, workflowID, fromID string, count int64, block time.Duration) ([]redissvc.StreamEntry, string, error)
	GetCheckpoint(ctx context.Context, workflowID string) (string, error)
	SetCheckpoint(ctx context.Context, workflowID, streamID string) error
	Stats() redissvc.Stats
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

type CardTemplate struct {
	TemplateID       string `json:"template_id"`
	Name             string `json:"name"`
	Description      string `json:"description,omitempty"`
	Scope            string `json:"scope"`
	OwnerUserID      string `json:"owner_user_id,omitempty"`
	Status           string `json:"status"`
	IsDefault        bool   `json:"is_default"`
	LatestVersion    int    `json:"latest_version"`
	VersionPublished bool   `json:"version_published"`
	CreatedAt        string `json:"created_at"`
	UpdatedAt        string `json:"updated_at"`
	Tags             any    `json:"tags,omitempty"`
	Metadata         any    `json:"metadata,omitempty"`
	FrontHTML        string `json:"-"`
	BackHTML         string `json:"-"`
	CSS              string `json:"-"`
	JS               string `json:"-"`
}

type TemplatePreference struct {
	UserID                 string `json:"user_id"`
	DefaultTemplateID      string `json:"default_template_id"`
	DefaultTemplateVersion int    `json:"default_template_version,omitempty"`
	UpdatedAt              string `json:"updated_at"`
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

type sseEvent struct {
	id      int64
	event   string
	payload []byte
}

type Server struct {
	port           int
	httpServer     *http.Server
	mux            *http.ServeMux
	httpClient     *http.Client
	ankiRuntimeURL string
	bgCancel       context.CancelFunc
	temporal       tclient.Client
	taskQueue      string
	redis          *redis.Client
	redisSvc       redisStreamClient

	taskService *application.TaskService
	sessionDB   *persistence.SessionStore

	mu                 sync.RWMutex
	timelineByWorkflow map[string][]TimelineEvent
	uploads            map[string]*uploadState

	subscribers    map[string]map[int]chan sseEvent
	streamReaders  map[string]context.CancelFunc
	subscriberSeq  int
	eventSeq       int64
	duplicateDrops int64
	seenStreamIDs  map[string]map[string]struct{}
	llmUsageIngested       int64
	llmUsageDeduped        int64
	llmUsageFailed         int64
	llmUsageInvalid        int64
	llmUsageSchemaMismatch int64
}

func NewServer(port int) *Server {
	if port == 0 {
		port = 50050
	}
	repo := persistence.NewInMemoryTaskRepository()
	publisher := persistence.NewInMemoryEventPublisher()
	taskService := application.NewTaskService(repo, publisher, nil)
	storeCfg := persistence.SessionStoreConfigFromEnv()
	sessionStore := persistence.NewSessionStore(context.Background(), storeCfg)

	temporalEnabled := strings.EqualFold(strings.TrimSpace(os.Getenv("ENABLE_TEMPORAL")), "true")
	temporalEndpoint := strings.TrimSpace(os.Getenv("TEMPORAL_ENDPOINT"))
	if temporalEndpoint == "" {
		temporalEndpoint = "temporal:7233"
	}
	taskQueue := strings.TrimSpace(os.Getenv("TASK_QUEUE"))
	if taskQueue == "" {
		taskQueue = "task-workflow-queue"
	}

	var temporalClient tclient.Client
	if temporalEnabled {
		if c, err := tclient.Dial(tclient.Options{HostPort: temporalEndpoint}); err != nil {
			log.Printf("warning: temporal enabled but dial failed: %v", err)
		} else {
			temporalClient = c
		}
	}

	var redisClient *redis.Client
	if storeCfg.RedisAddr != "" {
		rdb := redis.NewClient(&redis.Options{
			Addr:     storeCfg.RedisAddr,
			Password: storeCfg.RedisPassword,
			DB:       storeCfg.RedisDB,
		})
		if err := rdb.Ping(context.Background()).Err(); err != nil {
			log.Printf("warning: redis stream client ping failed: %v", err)
			_ = rdb.Close()
		} else {
			redisClient = rdb
		}
	}

	s := &Server{
		port:               port,
		mux:                http.NewServeMux(),
		httpClient:         &http.Client{Timeout: 5 * time.Second},
		ankiRuntimeURL:     strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL")),
		temporal:           temporalClient,
		taskQueue:          taskQueue,
		redis:              redisClient,
		redisSvc:           redissvc.NewService(redisClient),
		taskService:        taskService,
		sessionDB:          sessionStore,
		timelineByWorkflow: make(map[string][]TimelineEvent),
		uploads:            make(map[string]*uploadState),
		subscribers:        make(map[string]map[int]chan sseEvent),
		streamReaders:      make(map[string]context.CancelFunc),
		seenStreamIDs:      make(map[string]map[string]struct{}),
	}
	if s.ankiRuntimeURL == "" {
		s.ankiRuntimeURL = "http://anki-runtime:8012"
	}

	s.registerRoutes()
	publisher.AddHook(s.onDomainEvents)
	return s
}

func (s *Server) Handler() http.Handler {
	return s.withAuth(s.mux)
}

func (s *Server) Addr() string {
	return fmt.Sprintf(":%d", s.port)
}

func (s *Server) Start(ctx context.Context) error {
	if s.sessionDB != nil && s.sessionDB.Ready() {
		bgCtx, cancel := context.WithCancel(context.Background())
		s.bgCancel = cancel
		s.sessionDB.StartLifecycle(bgCtx)
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
	if s.sessionDB != nil {
		s.sessionDB.Close()
	}
	if s.temporal != nil {
		s.temporal.Close()
	}
	if s.redis != nil {
		_ = s.redis.Close()
	}
	if s.httpServer == nil {
		return nil
	}
	return s.httpServer.Shutdown(ctx)
}

func (s *Server) registerRoutes() {
	s.mux.HandleFunc("/api/v1/tasks", s.tasksHandler)
	s.mux.HandleFunc("/api/v1/tasks/batch", s.batchTasksHandler)
	s.mux.HandleFunc("/api/v1/tasks/template", s.templateTasksHandler)
	s.mux.HandleFunc("/api/v1/tasks/", s.taskDetailRouter)

	s.mux.HandleFunc("/api/v1/events", s.eventsHandler)
	s.mux.HandleFunc("/api/v1/stream/sse", s.sseHandler)

	s.mux.HandleFunc("/api/v1/sessions", s.sessionsHandler)
	s.mux.HandleFunc("/api/v1/sessions/", s.sessionsRouter)

	s.mux.HandleFunc("/api/v1/card-templates", s.cardTemplatesHandler)
	s.mux.HandleFunc("/api/v1/card-templates/preview", s.cardTemplatePreviewHandler)
	s.mux.HandleFunc("/api/v1/card-templates/validate", s.cardTemplateValidateHandler)
	s.mux.HandleFunc("/api/v1/card-templates/required-fields", s.cardTemplateRequiredFieldsHandler)
	s.mux.HandleFunc("/api/v1/card-templates/precheck", s.cardTemplatePrecheckHandler)
	s.mux.HandleFunc("/api/v1/card-templates/build-apkg", s.cardTemplateBuildApkgHandler)
	s.mux.HandleFunc("/api/v1/card-templates/", s.cardTemplateDetailHandler)
	s.mux.HandleFunc("/api/v1/users/me/template-preferences", s.userTemplatePreferencesHandler)

	s.mux.HandleFunc("/api/v1/schedules", s.schedulesHandler)
	s.mux.HandleFunc("/api/v1/schedules/", s.scheduleDetailHandler)

	s.mux.HandleFunc("/api/v1/cards/", s.cardsHandler)

	s.mux.HandleFunc("/api/v1/workflows/status", s.workflowStatusHandler)
	s.mux.HandleFunc("/api/v1/workflows/cancel", s.workflowCancelHandler)
	s.mux.HandleFunc("/api/v1/workflows/history", s.workflowHistoryHandler)

	s.mux.HandleFunc("/api/v1/files/upload/init", s.handleInitFileUpload)
	s.mux.HandleFunc("/api/v1/files/upload/chunk/", s.handleUploadChunk)
	s.mux.HandleFunc("/api/v1/files/upload/complete/", s.handleCompleteUpload)
	s.mux.HandleFunc("/api/v1/files/upload/status/", s.handleGetUploadStatus)

	s.mux.HandleFunc("/api/agents", s.agentsHandler)
	s.mux.HandleFunc("/health", s.healthHandler)
	s.mux.HandleFunc("/health/task-orchestrator", s.healthHandler)
	s.mux.HandleFunc("/", s.rootHandler)
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
