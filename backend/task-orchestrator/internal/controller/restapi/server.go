package restapi

import (
	"net/http"

	goagentstream "github.com/TekkenSteve/GoAgent/repo/stream"

	"task-orchestrator/internal/controller/restapi/v1"
	"task-orchestrator/internal/usecase"
)

type Server = v1.Server

type ServerDependencies struct {
	HTTPClient     *http.Client
	AnkiRuntimeURL string

	TaskService      *usecase.TaskService
	CommandService   *usecase.CommandService
	ReadModel        *usecase.ReadModelService
	WorkflowSvc      *usecase.WorkflowService
	SessionStore     v1.SessionLifecycleStore
	DefaultModelRef  string
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
		StreamSubscriber: deps.StreamSubscriber,
		StreamGateway:    deps.StreamGateway,
		CloseFuncs:       deps.CloseFuncs,
	})
}
