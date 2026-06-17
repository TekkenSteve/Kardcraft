package app

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/TekkenSteve/GoAgent/agentos"
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
		agentWorkflowBackend := usecase.AgentBackendRef{
			Kind: requiredEnv("AGENT_WORKFLOW_BACKEND_KIND"),
			Name: requiredEnv("AGENT_WORKFLOW_BACKEND_NAME"),
		}
		goagentRuntime, err := agentostemporal.NewRuntimeWithClient(context.Background(), agentostemporal.RuntimeConfig{
			TemporalTaskQueue: taskQueue,
			RedisURL:          redisURLFromConfig(storeCfg),
			TemporalExternalBackends: []agentostemporal.ExternalBackendConfig{
				{
					Name:         agentWorkflowBackend.Name,
					TaskQueue:    requiredEnv("AGENT_WORKFLOW_TASK_QUEUE"),
					WorkflowType: requiredEnv("AGENT_WORKFLOW_TYPE"),
					QueryType:    "agentos_status",
					Signals: agentostemporal.ExternalSignalNames{
						Pause:  "pause",
						Resume: "resume",
						Cancel: "cancel",
						Defaults: map[agentos.SignalType]string{
							agentos.SignalUserMessage: "user_input",
						},
					},
				},
			},
		}, temporalClient, agentostemporal.WithRunBackendIndex(goagentadapter.NewRunBackendIndex(persistent.NewAgentOSRunIndex(sessionStore))))
		if err != nil {
			log.Fatalf("failed to create GoAgent runtime: %v", err)
		}
		agentRuntime = goagentadapter.NewRuntime(goagentRuntime)
		commandSvc, err = command.New(
			taskService,
			restapi.NewCommandSessionStore(sessionStore),
			agentRuntime,
			agentWorkflowBackend,
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

func requiredEnv(key string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		log.Fatalf("%s is required", key)
	}
	return value
}
