package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	agentostemporal "github.com/TekkenSteve/GoAgent/agentos/temporal"
	gosdk "go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"task-orchestrator/internal/controller/temporal"
	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	endpoint := getenv("TEMPORAL_ENDPOINT", "temporal:7233")
	taskQueue := getenv("TASK_QUEUE", "task-workflow-queue")

	var c gosdk.Client
	var err error
	for i := range 30 {
		c, err = gosdk.NewClient(gosdk.Options{HostPort: endpoint})
		if err == nil {
			break
		}
		log.Printf("failed to connect temporal %s: %v (retry %d/30)", endpoint, err, i+1)
		time.Sleep(2 * time.Second)
	}
	if err != nil {
		log.Fatalf("failed to connect temporal after retries: %v", err)
	}
	defer c.Close()

	w := worker.New(c, taskQueue, worker.Options{})
	w.RegisterWorkflowWithOptions(temporal.TaskWorkflow, workflow.RegisterOptions{Name: usecase.TaskWorkflowName})
	storeCfg := persistent.SessionStoreConfigFromEnv()
	redisURL, err := storeCfg.RedisURL()
	if err != nil {
		log.Fatalf("invalid redis configuration: %v", err)
	}
	if redisURL == "" {
		log.Fatal("REDIS_HOST is required for task worker")
	}

	sessionStore := persistent.NewSessionStore(context.Background(), storeCfg)
	temporal.ConfigureTaskPersistenceStore(sessionStore)
	w.RegisterActivity(temporal.PersistTaskOutcomeActivity)

	llmConfigPath := strings.TrimSpace(os.Getenv("GOAGENT_LLM_CONFIG_PATH"))
	if llmConfigPath == "" {
		log.Fatal("GOAGENT_LLM_CONFIG_PATH is required for GoAgent worker kit")
	}
	workerKit, err := agentostemporal.NewWorkerKit(ctx, agentostemporal.WorkerConfig{
		TemporalAddress:       endpoint,
		TemporalTaskQueue:     taskQueue,
		PostgresURL:           storeCfg.PostgresDSN,
		RedisURL:              redisURL,
		LLMConfigPath:         llmConfigPath,
		LogLevel:              getenv("GOAGENT_LOG_LEVEL", "info"),
		RegisterEnvTools:      true,
		EnsureDefaultTemplate: false,
	})
	if err != nil {
		log.Fatalf("failed to create GoAgent worker kit: %v", err)
	}
	defer func() { _ = workerKit.Close() }()
	if err := workerKit.Register(w); err != nil {
		log.Fatalf("failed to register GoAgent worker kit: %v", err)
	}

	go func() {
		if err := w.Run(worker.InterruptCh()); err != nil {
			log.Fatalf("temporal worker stopped with error: %v", err)
		}
	}()

	log.Printf("temporal worker started, endpoint=%s queue=%s", endpoint, taskQueue)
	log.Printf("goagent worker kit registered")
	for {
		select {
		case <-ctx.Done():
			log.Println("task worker shutting down")
			return
		}
	}
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
