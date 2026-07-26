package v1

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/controller/restapi/middleware"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/schedule"
)

type SessionLifecycleStore interface {
	Ready() bool
	StartLifecycle(ctx context.Context)
	Close()
}

type Server struct {
	port                    int
	httpServer              *http.Server
	mux                     *http.ServeMux
	bgCancel                context.CancelFunc
	closeFuncs              []func()
	taskExecution           usecase.TaskExecution
	executionFeed           usecase.ExecutionEventFeed
	conversation            usecase.Conversation
	internalExecutionEvents http.Handler
	apkgExportService       usecase.APKGExport
	workspaceService        usecase.Workspace
	templateService         usecase.TemplateOperations
	taskPreparation         usecase.TaskInputPreparation

	taskService     usecase.Task
	commandService  usecase.Command
	readModel       usecase.ReadModel
	sessionStore    SessionLifecycleStore
	defaultModelRef string
	scheduleService *schedule.Service
}

type ServerDependencies struct {
	TaskService             usecase.Task
	CommandService          usecase.Command
	ReadModel               usecase.ReadModel
	SessionStore            SessionLifecycleStore
	DefaultModelRef         string
	TaskExecution           usecase.TaskExecution
	ExecutionFeed           usecase.ExecutionEventFeed
	Conversation            usecase.Conversation
	InternalExecutionEvents http.Handler
	APKGExportService       usecase.APKGExport
	WorkspaceService        usecase.Workspace
	TemplateService         usecase.TemplateOperations
	TaskPreparation         usecase.TaskInputPreparation
	ScheduleService         *schedule.Service

	CloseFuncs []func()
}

func NewServer(port int, deps ServerDependencies) *Server {
	if port == 0 {
		port = 50050
	}
	s := &Server{
		port:                    port,
		mux:                     http.NewServeMux(),
		closeFuncs:              deps.CloseFuncs,
		taskExecution:           deps.TaskExecution,
		executionFeed:           deps.ExecutionFeed,
		conversation:            deps.Conversation,
		internalExecutionEvents: deps.InternalExecutionEvents,
		apkgExportService:       deps.APKGExportService,
		workspaceService:        deps.WorkspaceService,
		templateService:         deps.TemplateService,
		taskPreparation:         deps.TaskPreparation,
		taskService:             deps.TaskService,
		commandService:          deps.CommandService,
		readModel:               deps.ReadModel,
		sessionStore:            deps.SessionStore,
		defaultModelRef:         strings.TrimSpace(deps.DefaultModelRef),
		scheduleService:         deps.ScheduleService,
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

func (s *Server) nextWorkflowID(taskType string) string {
	name := strings.TrimSpace(taskType)
	if name == "" {
		name = "main"
	}
	return fmt.Sprintf("workflow_%s_%d", name, time.Now().UTC().UnixNano())
}

func (s *Server) isTaskExecutionAvailable() bool {
	return s.taskExecution != nil
}

func (s *Server) authorizeTaskAccess(ctx context.Context, userID string, taskID string) bool {
	return AuthorizeTaskAccess(ctx, s.readModel, userID, taskID)
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
