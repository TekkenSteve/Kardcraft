package app

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	goredis "github.com/redis/go-redis/v9"
	tclient "go.temporal.io/sdk/client"

	"github.com/TekkenSteve/GoAgent/agentfw/config"
	goagentredis "github.com/TekkenSteve/GoAgent/pkg/redis"
	goagentpersistent "github.com/TekkenSteve/GoAgent/repo/persistent"
	goagentstream "github.com/TekkenSteve/GoAgent/repo/stream"
	"github.com/TekkenSteve/GoAgent/usecase/executor"

	restapi "task-orchestrator/internal/controller/restapi/v1"
	v1adapters "task-orchestrator/internal/controller/restapi/v1/adapters"
	"task-orchestrator/internal/repo/persistent"
	redissvc "task-orchestrator/internal/repo/redis"
	"task-orchestrator/internal/usecase"
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

	var redisClient *goredis.Client
	var streamClient *v1adapters.RedisStreamClient
	var goagentSubscriber *goagentstream.RedisSubscriber
	var goagentGateway *goagentstream.SSEGateway
	if storeCfg.RedisAddr != "" {
		rdb, err := redissvc.NewStreamClient(context.Background(), storeCfg.RedisAddr, storeCfg.RedisPassword, storeCfg.RedisDB)
		if err != nil {
			log.Printf("warning: redis stream client ping failed: %v", err)
		} else {
			redisClient = rdb
			streamClient = v1adapters.NewRedisStreamClient(redissvc.NewService(redisClient))
		}

		redisURL := fmt.Sprintf("redis://%s/%d", storeCfg.RedisAddr, storeCfg.RedisDB)
		if storeCfg.RedisPassword != "" {
			redisURL = fmt.Sprintf("redis://:%s@%s/%d", storeCfg.RedisPassword, storeCfg.RedisAddr, storeCfg.RedisDB)
		}
		goagentRDB, err := goagentredis.New(context.Background(), redisURL)
		if err != nil {
			log.Printf("warning: goagent redis client creation failed: %v", err)
		} else {
			goagentSubscriber = goagentstream.NewRedisSubscriber(goagentRDB.Hub())
			goagentGateway = goagentstream.NewSSEGateway()
		}
	}

	repo := persistent.NewInMemoryTaskRepository()
	publisher := persistent.NewInMemoryEventPublisher()
	taskService := usecase.NewTaskService(repo, publisher, nil)

	readModel := usecase.NewReadModelService(readModelStore)
	workflowSvc := usecase.NewWorkflowService(v1adapters.NewTemporalWorkflowRuntime(temporalClient), readModelStore)

	var commandSvc *usecase.CommandService
	if temporalClient != nil {
		executorTemporal := goagentpersistent.NewExecutorTemporal(temporalClient, config.Temporal{
			TaskQueue: taskQueue,
		})
		agentExecutor := executor.New(executorTemporal)
		commandSvc = usecase.NewCommandService(
			taskService,
			v1adapters.NewCommandSessionStore(sessionStore),
			agentExecutor,
			v1adapters.NewTemporalCommandRuntime(temporalClient, taskQueue),
		)
	}

	closeFuncs := make([]func(), 0, 2)
	if temporalClient != nil {
		closeFuncs = append(closeFuncs, temporalClient.Close)
	}
	if redisClient != nil {
		closeFuncs = append(closeFuncs, func() { _ = redisClient.Close() })
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
		RedisSvc:         streamClient,
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
