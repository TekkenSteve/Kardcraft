package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	tclient "go.temporal.io/sdk/client"

	httpserver "task-orchestrator/internal/controller/http/v1"
	v1adapters "task-orchestrator/internal/controller/http/v1/adapters"
	"task-orchestrator/internal/repo/persistence"
	redissvc "task-orchestrator/internal/repo/redis"
	"task-orchestrator/internal/usecase"
)

func buildServerFromEnv() *httpserver.Server {
	storeCfg := persistence.SessionStoreConfigFromEnv()
	sessionStore := persistence.NewSessionStore(context.Background(), storeCfg)
	readModelStore := persistence.NewUsecaseReadModelStore(sessionStore)

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

	var redisClient *redis.Client
	var streamClient *v1adapters.RedisStreamClient
	if storeCfg.RedisAddr != "" {
		rdb := redis.NewClient(&redis.Options{
			Addr:     storeCfg.RedisAddr,
			Password: storeCfg.RedisPassword,
			DB:       storeCfg.RedisDB,
		})
		if err := rdb.Ping(context.Background()).Err(); err != nil {
			log.Printf("warning: redis stream client ping failed: %v", err)
			_ = rdb.Close()
		} else {
			redisClient = rdb
			streamClient = v1adapters.NewRedisStreamClient(redissvc.NewService(redisClient))
		}
	}

	repo := persistence.NewInMemoryTaskRepository()
	publisher := persistence.NewInMemoryEventPublisher()
	taskService := usecase.NewTaskService(repo, publisher, nil)

	readModel := usecase.NewReadModelService(readModelStore)
	workflowSvc := usecase.NewWorkflowService(v1adapters.NewTemporalWorkflowRuntime(temporalClient), readModelStore)

	var commandSvc *usecase.CommandService
	if temporalClient != nil {
		commandSvc = usecase.NewCommandService(
			taskService,
			v1adapters.NewCommandSessionStore(sessionStore),
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

	srv := httpserver.NewServer(defaultPortFromEnv(), httpserver.ServerDependencies{
		HTTPClient:     &http.Client{Timeout: 5 * time.Second},
		AnkiRuntimeURL: strings.TrimSpace(os.Getenv("ANKI_RUNTIME_URL")),
		TaskService:    taskService,
		CommandService: commandSvc,
		ReadModel:      readModel,
		WorkflowSvc:    workflowSvc,
		SessionStore:   sessionStore,
		RedisSvc:       streamClient,
		CloseFuncs:     closeFuncs,
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
