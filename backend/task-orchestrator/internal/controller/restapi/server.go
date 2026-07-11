package restapi

import (
	"net/http"

	"task-orchestrator/internal/controller/restapi/v1"
	"task-orchestrator/internal/usecase"
)

type Server = v1.Server

type ServerDependencies struct {
	HTTPClient     *http.Client
	AnkiRuntimeURL string

	TaskService     usecase.Task
	CommandService  usecase.Command
	ReadModel       usecase.ReadModel
	SessionStore    v1.SessionLifecycleStore
	DefaultModelRef string
	AgentRuntime    usecase.AgentRuntime

	CloseFuncs []func()
}

func NewServer(port int, deps ServerDependencies) *Server {
	return v1.NewServer(port, v1.ServerDependencies{
		HTTPClient:      deps.HTTPClient,
		AnkiRuntimeURL:  deps.AnkiRuntimeURL,
		TaskService:     deps.TaskService,
		CommandService:  deps.CommandService,
		ReadModel:       deps.ReadModel,
		SessionStore:    deps.SessionStore,
		DefaultModelRef: deps.DefaultModelRef,
		AgentRuntime:    deps.AgentRuntime,
		CloseFuncs:      deps.CloseFuncs,
	})
}
