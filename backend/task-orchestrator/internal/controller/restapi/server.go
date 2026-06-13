package restapi

import (
	"net/http"

	goagentstream "github.com/TekkenSteve/GoAgent/repo/stream"

	"task-orchestrator/internal/controller/restapi/v1"
	redissvc "task-orchestrator/internal/repo/redis"
	"task-orchestrator/internal/usecase"
)

type Server = v1.Server

type RedisStreamClient = v1.RedisStreamClient

type ServerDependencies struct {
	HTTPClient     *http.Client
	AnkiRuntimeURL string

	TaskService      *usecase.TaskService
	CommandService   *usecase.CommandService
	ReadModel        *usecase.ReadModelService
	WorkflowSvc      *usecase.WorkflowService
	SessionStore     v1.SessionLifecycleStore
	DefaultModelRef  string
	RedisSvc         v1.RedisStreamClientPort
	StreamSubscriber *goagentstream.RedisSubscriber
	StreamGateway    *goagentstream.SSEGateway

	CloseFuncs []func()
}

func NewServer(port int, deps ServerDependencies) *Server {
	return v1.NewServer(port, v1.ServerDependencies{
		HTTPClient:       deps.HTTPClient,
		AnkiRuntimeURL:   deps.AnkiRuntimeURL,
		TaskService:      deps.TaskService,
		CommandService:   deps.CommandService,
		ReadModel:        deps.ReadModel,
		WorkflowSvc:      deps.WorkflowSvc,
		SessionStore:     deps.SessionStore,
		DefaultModelRef:  deps.DefaultModelRef,
		RedisSvc:         deps.RedisSvc,
		StreamSubscriber: deps.StreamSubscriber,
		StreamGateway:    deps.StreamGateway,
		CloseFuncs:       deps.CloseFuncs,
	})
}

func NewRedisStreamClient(svc *redissvc.Service) *RedisStreamClient {
	return v1.NewRedisStreamClient(svc)
}
