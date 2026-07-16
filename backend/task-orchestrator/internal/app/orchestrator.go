package app

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	agentosproc "github.com/TekkenSteve/GoAgent/agentos/process"
	agentostemporal "github.com/TekkenSteve/GoAgent/agentos/temporal"
	tclient "go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"

	"task-orchestrator/internal/adapter/anki"
	goagentadapter "task-orchestrator/internal/adapter/goagent"
	"task-orchestrator/internal/adapter/hydra"
	agentosconfig "task-orchestrator/internal/app/agentos"
	"task-orchestrator/internal/controller/internalapi"
	"task-orchestrator/internal/controller/restapi"
	"task-orchestrator/internal/repo/memory"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/apkgexport"
	"task-orchestrator/internal/usecase/command"
	"task-orchestrator/internal/usecase/execution"
	"task-orchestrator/internal/usecase/readmodel"
	"task-orchestrator/internal/usecase/schedule"
	"task-orchestrator/internal/usecase/task"
	"task-orchestrator/internal/usecase/taskpreparation"
	templateusecase "task-orchestrator/internal/usecase/template"
	"task-orchestrator/internal/usecase/workspace"
)

func NewOrchestratorFromEnv() *restapi.Server {
	storeCfg := persistent.SessionStoreConfigFromEnv()
	sessionStore := persistent.NewSessionStore(context.Background(), storeCfg)
	readModelStore := persistent.NewUsecaseReadModelStore(sessionStore)
	httpClient := &http.Client{Timeout: 5 * time.Second}

	var temporalClient tclient.Client
	var temporalEndpoint string
	if strings.EqualFold(strings.TrimSpace(os.Getenv("ENABLE_TEMPORAL")), "true") {
		temporalEndpoint = strings.TrimSpace(os.Getenv("TEMPORAL_ENDPOINT"))
		if temporalEndpoint == "" {
			temporalEndpoint = "temporal:7233"
		}
		client, err := tclient.Dial(tclient.Options{HostPort: temporalEndpoint})
		if err != nil {
			log.Fatalf("Temporal is enabled but unavailable: %v", err)
		} else {
			temporalClient = client
		}
	}

	taskRepo := memory.NewInMemoryTaskRepository()
	publisher := memory.NewInMemoryEventPublisher()
	taskService := task.New(taskRepo, publisher, nil)

	readModel := readmodel.New(readModelStore)
	workspaceService, err := workspace.New(readModel)
	if err != nil {
		log.Fatalf("failed to create workspace service: %v", err)
	}
	taskPreparation, err := taskpreparation.New(readModel, workspaceService)
	if err != nil {
		log.Fatalf("failed to create task input preparation service: %v", err)
	}
	exportService, err := apkgexport.New(readModel, persistent.NewAPKGExportStore(sessionStore))
	if err != nil {
		log.Fatalf("failed to create APKG export service: %v", err)
	}
	ankiRuntimeURL := strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL"))
	if ankiRuntimeURL == "" {
		ankiRuntimeURL = "http://anki-runtime:8012"
	}
	ankiClient, err := anki.NewClient(httpClient, ankiRuntimeURL)
	if err != nil {
		log.Fatalf("failed to create Anki runtime client: %v", err)
	}
	templateService, err := templateusecase.New(readModel, ankiClient)
	if err != nil {
		log.Fatalf("failed to create template service: %v", err)
	}
	exportWorker, err := apkgexport.NewWorker(readModel, persistent.NewAPKGExportStore(sessionStore), ankiClient)
	if err != nil {
		log.Fatalf("failed to create APKG export worker: %v", err)
	}
	riverClient, err := persistent.NewAPKGExportWorkerClient(sessionStore, exportWorker)
	if err != nil {
		log.Fatalf("failed to create APKG export queue client: %v", err)
	}
	riverContext, stopRiver := context.WithCancel(context.Background())
	if err := riverClient.Start(riverContext); err != nil {
		stopRiver()
		log.Fatalf("failed to start APKG export queue: %v", err)
	}
	var commandSvc usecase.Command
	var taskExecution usecase.TaskExecution
	var executionFeed usecase.ExecutionEventFeed
	var internalExecutionEvents http.Handler
	var scheduleService *schedule.Service
	var triggerDispatchQueue string
	closeFuncs := make([]func(), 0, 9)
	closeFuncs = append(closeFuncs, func() {
		stopRiver()
		if err := riverClient.Stop(context.Background()); err != nil {
			log.Printf("stop APKG export queue: %v", err)
		}
	})
	if temporalClient != nil {
		externalRuntime, err := agentosconfig.ExternalRuntimeConfigFromEnv(storeCfg)
		if err != nil {
			log.Fatalf("failed to configure GoAgent external runtime: %v", err)
		}
		externalRuntime.Runtime.TemporalAddress = temporalEndpoint
		planRuntime, err := agentostemporal.NewPlanRuntimeWithClient(
			context.Background(),
			&externalRuntime.Runtime,
			temporalClient,
		)
		if err != nil {
			log.Fatalf("failed to create GoAgent plan runtime: %v", err)
		}
		triggerDispatchQueue = externalRuntime.Runtime.TemporalTaskQueues.PlanControl
		executionRoutes := persistent.NewTaskExecutionIndex(sessionStore)
		taskExecution, err = goagentadapter.NewTaskExecution(
			planRuntime,
			executionRoutes,
			goagentadapter.TaskExecutionConfig{
				NodeID:  "langgraph",
				Backend: externalRuntime.Backend,
			},
		)
		if err != nil {
			log.Fatalf("failed to create task execution adapter: %v", err)
		}
		executionFeed, err = execution.NewFeed(taskExecution)
		if err != nil {
			log.Fatalf("failed to create task execution feed: %v", err)
		}
		projector, err := execution.NewProjector(taskExecution, executionRoutes, sessionStore)
		if err != nil {
			log.Fatalf("failed to create execution projector: %v", err)
		}
		projectorContext, stopProjector := context.WithCancel(context.Background())
		go projector.Run(projectorContext, 5*time.Second)
		closeFuncs = append(closeFuncs, stopProjector)
		introspector, err := hydra.NewIntrospector(httpClient, hydra.IntrospectionConfig{
			Endpoint:         strings.TrimSpace(os.Getenv("HYDRA_INTROSPECTION_URL")),
			ClientID:         strings.TrimSpace(os.Getenv("TASK_ORCHESTRATOR_OAUTH_CLIENT_ID")),
			ClientSecret:     strings.TrimSpace(os.Getenv("TASK_ORCHESTRATOR_OAUTH_CLIENT_SECRET")),
			RequiredScope:    "task.events.write",
			RequiredClient:   "agent-workflow",
			RequiredAudience: strings.TrimSpace(os.Getenv("HYDRA_EVENT_AUDIENCE")),
		})
		if err != nil {
			log.Fatalf("failed to configure internal service authentication: %v", err)
		}
		internalExecutionEvents = internalapi.NewExecutionEventsHandler(internalapi.ExecutionEventsDeps{
			Validator: introspector,
			Execution: taskExecution,
		})
		planWorkerConfig := agentosconfig.PlanWorkerConfig(externalRuntime.Runtime)
		planWorkerKit, err := agentostemporal.NewPlanWorkerKit(context.Background(), &planWorkerConfig)
		if err != nil {
			log.Fatalf("failed to construct GoAgent plan worker kit: %v", err)
		}
		planControlWorker := worker.New(temporalClient, externalRuntime.Runtime.TemporalTaskQueues.PlanControl, worker.Options{})
		planActivityWorker := worker.New(temporalClient, externalRuntime.Runtime.TemporalTaskQueues.PlanActivity, worker.Options{})
		if err := planWorkerKit.Register(&agentostemporal.PlanWorkerSet{Control: planControlWorker, Activity: planActivityWorker}); err != nil {
			_ = planWorkerKit.Close()
			log.Fatalf("failed to register GoAgent plan workloads: %v", err)
		}
		if err := planControlWorker.Start(); err != nil {
			_ = planWorkerKit.Close()
			log.Fatalf("failed to start GoAgent plan control worker: %v", err)
		}
		if err := planActivityWorker.Start(); err != nil {
			planControlWorker.Stop()
			_ = planWorkerKit.Close()
			log.Fatalf("failed to start GoAgent plan activity worker: %v", err)
		}
		planRecovery, err := planWorkerKit.StartPlanCommandRecovery(context.Background(), agentostemporal.PlanCommandRecoveryLoopConfig{RecoverImmediately: true}, nil)
		if err != nil {
			planActivityWorker.Stop()
			planControlWorker.Stop()
			_ = planWorkerKit.Close()
			log.Fatalf("failed to start GoAgent plan command recovery: %v", err)
		}
		closeFuncs = append(closeFuncs,
			planRecovery.Stop,
			planActivityWorker.Stop,
			planControlWorker.Stop,
			func() { _ = planWorkerKit.Close() },
		)
		commandSvc, err = command.New(
			taskService,
			restapi.NewCommandSessionStore(sessionStore),
			taskExecution,
			readModel,
		)
		if err != nil {
			log.Fatalf("failed to create command usecase: %v", err)
		}
	}

	if temporalClient != nil {
		closeFuncs = append(closeFuncs, temporalClient.Close)
	}
	if closer, ok := taskExecution.(interface{ Close() error }); ok {
		closeFuncs = append(closeFuncs, func() { _ = closer.Close() })
	}
	if temporalClient != nil {
		scheduleTriggerConfig, err := agentosconfig.ScheduleTriggerConfigFromEnv()
		if err != nil {
			log.Fatalf("failed to configure Kardcraft schedule trigger: %v", err)
		}
		triggerRuntime, err := agentostemporal.NewTriggerRuntime(temporalClient, triggerDispatchQueue)
		if err != nil {
			log.Fatalf("failed to create GoAgent trigger runtime: %v", err)
		}
		scheduleRuntime, err := goagentadapter.NewScheduleTriggerRuntime(triggerRuntime, goagentadapter.ScheduleTriggerRuntimeConfig(scheduleTriggerConfig))
		if err != nil {
			log.Fatalf("failed to create Kardcraft schedule trigger adapter: %v", err)
		}
		scheduleService = schedule.New(sessionStore, scheduleRuntime, commandSvc, readModel)
		if err := scheduleService.Reconcile(context.Background()); err != nil {
			log.Fatalf("failed to reconcile Kardcraft schedules into GoAgent: %v", err)
		}
		stopWorker, err := agentostemporal.StartTriggerWorker(temporalClient, triggerDispatchQueue, func(ctx context.Context, delivery agentosproc.TriggerDelivery) error {
			scheduleDelivery, err := goagentadapter.ScheduleDeliveryFromTrigger(delivery)
			if err != nil {
				return err
			}

			return scheduleService.Dispatch(ctx, scheduleDelivery)
		})
		if err != nil {
			log.Fatalf("failed to start GoAgent trigger worker: %v", err)
		}
		closeFuncs = append(closeFuncs, stopWorker)
	}

	srv := restapi.NewServer(defaultPortFromEnv(), restapi.ServerDependencies{
		TaskService:             taskService,
		CommandService:          commandSvc,
		ReadModel:               readModel,
		SessionStore:            sessionStore,
		DefaultModelRef:         strings.TrimSpace(os.Getenv("GOAGENT_MODEL_REF")),
		TaskExecution:           taskExecution,
		ExecutionFeed:           executionFeed,
		InternalExecutionEvents: internalExecutionEvents,
		APKGExportService:       exportService,
		WorkspaceService:        workspaceService,
		TemplateService:         templateService,
		TaskPreparation:         taskPreparation,
		ScheduleService:         scheduleService,
		CloseFuncs:              closeFuncs,
	})
	return srv
}

func defaultPortFromEnv() int {
	raw := strings.TrimSpace(os.Getenv("PORT"))
	if raw == "" {
		return 50050
	}
	port, err := strconv.Atoi(raw)
	if err != nil || port <= 0 {
		return 50050
	}
	return port
}
