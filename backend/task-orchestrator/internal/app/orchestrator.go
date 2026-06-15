package app

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	agentostemporal "github.com/TekkenSteve/GoAgent/agentos/temporal"
	tclient "go.temporal.io/sdk/client"

	goagentadapter "task-orchestrator/internal/adapter/goagent"
	"task-orchestrator/internal/controller/restapi"
	"task-orchestrator/internal/repo/memory"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/command"
	"task-orchestrator/internal/usecase/readmodel"
	"task-orchestrator/internal/usecase/task"
	"task-orchestrator/internal/usecase/workflow"
)

func NewOrchestratorFromEnv() *restapi.Server {
	storeCfg := persistent.SessionStoreConfigFromEnv()
	sessionStore := persistent.NewSessionStore(context.Background(), storeCfg)
	readModelStore := persistent.NewUsecaseReadModelStore(sessionStore)

	taskQueue := strings.TrimSpace(os.Getenv("TASK_QUEUE"))
	if taskQueue == "" {
		taskQueue = "task-workflow-queue"
	}

	var temporalClient tclient.Client
	if strings.EqualFold(strings.TrimSpace(os.Getenv("ENABLE_TEMPORAL")), "true") {
		temporalEndpoint := strings.TrimSpace(os.Getenv("TEMPORAL_ENDPOINT"))
		if temporalEndpoint == "" {
			temporalEndpoint = "temporal:7233"
		}
		client, err := tclient.Dial(tclient.Options{HostPort: temporalEndpoint})
		if err != nil {
			log.Printf("warning: temporal enabled but dial failed: %v", err)
		} else {
			temporalClient = client
		}
	}

	taskRepo := memory.NewInMemoryTaskRepository()
	publisher := memory.NewInMemoryEventPublisher()
	taskService := task.New(taskRepo, publisher, nil)

	readModel := readmodel.New(readModelStore)
	workflowSvc := workflow.New(restapi.NewTemporalWorkflowRuntime(temporalClient), readModelStore)

	var commandSvc usecase.Command
	var agentRuntime usecase.AgentRuntime
	if temporalClient != nil {
		goagentRuntime, err := agentostemporal.NewRuntimeWithClient(context.Background(), agentostemporal.RuntimeConfig{
			TemporalTaskQueue: taskQueue,
			RedisURL:          redisURLFromConfig(storeCfg),
		}, temporalClient)
		if err != nil {
			log.Fatalf("failed to create GoAgent runtime: %v", err)
		}
		agentRuntime = goagentadapter.NewRuntime(goagentRuntime)
		commandSvc = command.New(
			taskService,
			restapi.NewCommandSessionStore(sessionStore),
			agentRuntime,
			restapi.NewTemporalCommandRuntime(temporalClient, taskQueue),
		)
	}

	closeFuncs := make([]func(), 0, 2)
	if temporalClient != nil {
		closeFuncs = append(closeFuncs, temporalClient.Close)
	}
	if closer, ok := agentRuntime.(interface{ Close() error }); ok {
		closeFuncs = append(closeFuncs, func() { _ = closer.Close() })
	}

	srv := restapi.NewServer(defaultPortFromEnv(), restapi.ServerDependencies{
		HTTPClient:      &http.Client{Timeout: 5 * time.Second},
		AnkiRuntimeURL:  strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL")),
		TaskService:     taskService,
		CommandService:  commandSvc,
		ReadModel:       readModel,
		WorkflowSvc:     workflowSvc,
		SessionStore:    sessionStore,
		DefaultModelRef: strings.TrimSpace(os.Getenv("GOAGENT_MODEL_REF")),
		AgentRuntime:    agentRuntime,
		CloseFuncs:      closeFuncs,
	})
	publisher.AddHook(srv.ProjectDomainEvents)
	return srv
}

func redisURLFromConfig(cfg persistent.SessionStoreConfig) string {
	redisURL, err := cfg.RedisURL()
	if err != nil {
		log.Fatalf("invalid redis configuration: %v", err)
	}
	return redisURL
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
