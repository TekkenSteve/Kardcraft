package restapi

import (
	"net/http"

	"task-orchestrator/internal/controller/restapi/v1"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/schedule"
)

type Server = v1.Server

type ServerDependencies struct {
	TaskService             usecase.Task
	CommandService          usecase.Command
	ReadModel               usecase.ReadModel
	SessionStore            v1.SessionLifecycleStore
	DefaultModelRef         string
	TaskExecution           usecase.TaskExecution
	ExecutionFeed           usecase.ExecutionEventFeed
	InternalExecutionEvents http.Handler
	APKGExportService       usecase.APKGExport
	WorkspaceService        usecase.Workspace
	TemplateService         usecase.TemplateOperations
	TaskPreparation         usecase.TaskInputPreparation
	ScheduleService         *schedule.Service

	CloseFuncs []func()
}

func NewServer(port int, deps ServerDependencies) *Server {
	return v1.NewServer(port, v1.ServerDependencies{
		TaskService:             deps.TaskService,
		CommandService:          deps.CommandService,
		ReadModel:               deps.ReadModel,
		SessionStore:            deps.SessionStore,
		DefaultModelRef:         deps.DefaultModelRef,
		TaskExecution:           deps.TaskExecution,
		ExecutionFeed:           deps.ExecutionFeed,
		InternalExecutionEvents: deps.InternalExecutionEvents,
		APKGExportService:       deps.APKGExportService,
		WorkspaceService:        deps.WorkspaceService,
		TemplateService:         deps.TemplateService,
		TaskPreparation:         deps.TaskPreparation,
		ScheduleService:         deps.ScheduleService,
		CloseFuncs:              deps.CloseFuncs,
	})
}
