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

	goagentadapter "task-orchestrator/internal/adapter/goagent"
	agentosconfig "task-orchestrator/internal/app/agentos"
	"task-orchestrator/internal/controller/restapi"
	"task-orchestrator/internal/repo/memory"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/command"
	"task-orchestrator/internal/usecase/readmodel"
	"task-orchestrator/internal/usecase/schedule"
	"task-orchestrator/internal/usecase/task"
)

func NewOrchestratorFromEnv() *restapi.Server {
	storeCfg := persistent.SessionStoreConfigFromEnv()
	sessionStore := persistent.NewSessionStore(context.Background(), storeCfg)
	readModelStore := persistent.NewUsecaseReadModelStore(sessionStore)

	var temporalClient tclient.Client
	if strings.EqualFold(strings.TrimSpace(os.Getenv("ENABLE_TEMPORAL")), "true") {
		temporalEndpoint := strings.TrimSpace(os.Getenv("TEMPORAL_ENDPOINT"))
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
	var commandSvc usecase.Command
	var agentRuntime usecase.AgentRuntime
	var scheduleService *schedule.Service
	var triggerDispatchQueue string
	if temporalClient != nil {
		externalRuntime, err := agentosconfig.ExternalRuntimeConfigFromEnv(storeCfg)
		if err != nil {
			log.Fatalf("failed to configure GoAgent external runtime: %v", err)
		}
		goagentRuntime, err := agentostemporal.NewRuntimeWithClient(
			context.Background(),
			&externalRuntime.Runtime,
			temporalClient,
			agentostemporal.WithRunBackendIndex(goagentadapter.NewRunBackendIndex(persistent.NewAgentOSRunIndex(sessionStore))),
		)
		if err != nil {
			log.Fatalf("failed to create GoAgent runtime: %v", err)
		}
		triggerDispatchQueue = externalRuntime.Runtime.TemporalTaskQueues.PlanControl
		agentRuntime = goagentadapter.NewRuntime(goagentRuntime)
		commandSvc, err = command.New(
			taskService,
			restapi.NewCommandSessionStore(sessionStore),
			agentRuntime,
			externalRuntime.Backend,
		)
		if err != nil {
			log.Fatalf("failed to create command usecase: %v", err)
		}
	}

	closeFuncs := make([]func(), 0, 2)
	if temporalClient != nil {
		closeFuncs = append(closeFuncs, temporalClient.Close)
	}
	if closer, ok := agentRuntime.(interface{ Close() error }); ok {
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
		HTTPClient:      &http.Client{Timeout: 5 * time.Second},
		AnkiRuntimeURL:  strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL")),
		TaskService:     taskService,
		CommandService:  commandSvc,
		ReadModel:       readModel,
		SessionStore:    sessionStore,
		DefaultModelRef: strings.TrimSpace(os.Getenv("GOAGENT_MODEL_REF")),
		AgentRuntime:    agentRuntime,
		ScheduleService: scheduleService,
		CloseFuncs:      closeFuncs,
	})
	publisher.AddHook(srv.ProjectDomainEvents)
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
