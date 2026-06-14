package app

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	tclient "go.temporal.io/sdk/client"

	"github.com/TekkenSteve/GoAgent/agentfw/config"
	goagentredis "github.com/TekkenSteve/GoAgent/pkg/redis"
	goagentpersistent "github.com/TekkenSteve/GoAgent/repo/persistent"
	goagentstream "github.com/TekkenSteve/GoAgent/repo/stream"
	"github.com/TekkenSteve/GoAgent/usecase/executor"

	"task-orchestrator/internal/controller/restapi"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
)

func NewOrchestratorFromEnv() *restapi.Server {
	storeCfg := persistent.SessionStoreConfigFromEnv()

	var goagentRedis *goagentredis.Redis
	var goagentSubscriber *goagentstream.RedisSubscriber
	var goagentGateway *goagentstream.SSEGateway
	if redisURL, err := storeCfg.GoAgentRedisURL(); err != nil {
		log.Fatalf("invalid redis configuration: %v", err)
	} else if redisURL != "" {
		rdb, err := goagentredis.New(context.Background(), redisURL)
		if err != nil {
			log.Printf("warning: goagent redis client creation failed: %v", err)
		} else {
			goagentRedis = rdb
			goagentSubscriber = goagentstream.NewRedisSubscriber(rdb.Hub())
			goagentGateway = goagentstream.NewSSEGateway()
		}
	}

	sessionStore := persistent.NewSessionStoreWithRedis(context.Background(), storeCfg, goagentRedis)
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

	repo := persistent.NewInMemoryTaskRepository()
	publisher := persistent.NewInMemoryEventPublisher()
	taskService := usecase.NewTaskService(repo, publisher, nil)

	readModel := usecase.NewReadModelService(readModelStore)
	workflowSvc := usecase.NewWorkflowService(restapi.NewTemporalWorkflowRuntime(temporalClient), readModelStore)

	var commandSvc *usecase.CommandService
	if temporalClient != nil {
		executorTemporal := goagentpersistent.NewExecutorTemporal(temporalClient, config.Temporal{
			TaskQueue: taskQueue,
		})
		agentExecutor := executor.New(executorTemporal)
		commandSvc = usecase.NewCommandService(
			taskService,
			restapi.NewCommandSessionStore(sessionStore),
			agentExecutor,
			restapi.NewTemporalCommandRuntime(temporalClient, taskQueue),
		)
	}

	closeFuncs := make([]func(), 0, 2)
	if temporalClient != nil {
		closeFuncs = append(closeFuncs, temporalClient.Close)
	}
	if goagentRedis != nil {
		closeFuncs = append(closeFuncs, func() { _ = goagentRedis.Close() })
	}

	srv := restapi.NewServer(defaultPortFromEnv(), restapi.ServerDependencies{
		HTTPClient:       &http.Client{Timeout: 5 * time.Second},
		AnkiRuntimeURL:   strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL")),
		TaskService:      taskService,
		CommandService:   commandSvc,
		ReadModel:        readModel,
		WorkflowSvc:      workflowSvc,
		SessionStore:     sessionStore,
		DefaultModelRef:  strings.TrimSpace(os.Getenv("GOAGENT_MODEL_REF")),
		StreamSubscriber: goagentSubscriber,
		StreamGateway:    goagentGateway,
		CloseFuncs:       closeFuncs,
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
