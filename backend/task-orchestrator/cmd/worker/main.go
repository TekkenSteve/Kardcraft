package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	schemas "github.com/maximhq/bifrost/core/schemas"
	goredis "github.com/redis/go-redis/v9"
	gosdk "go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"

	"github.com/TekkenSteve/GoAgent/agentfw/orchestration"
	agentruntime "github.com/TekkenSteve/GoAgent/agentfw/runtime"
	agenttool "github.com/TekkenSteve/GoAgent/agentfw/tool"
	"github.com/TekkenSteve/GoAgent/pkg/logger"
	goagentredis "github.com/TekkenSteve/GoAgent/pkg/redis"
	"github.com/TekkenSteve/GoAgent/repo/compressor"
	"github.com/TekkenSteve/GoAgent/repo/framework"
	"github.com/TekkenSteve/GoAgent/repo/pipeline"
	goagentstream "github.com/TekkenSteve/GoAgent/repo/stream"
	"github.com/TekkenSteve/GoAgent/repo/toolkit"
	"github.com/TekkenSteve/GoAgent/repo/webapi"
	agentuc "github.com/TekkenSteve/GoAgent/usecase/agent"

	"task-orchestrator/internal/controller/temporal/workflows"
	"task-orchestrator/internal/repo/persistent"
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
	w.RegisterWorkflow(workflows.TaskWorkflow)
	sessionStore := persistent.NewSessionStore(context.Background(), persistent.SessionStoreConfigFromEnv())
	workflows.ConfigureTaskPersistenceStore(sessionStore)
	w.RegisterActivity(workflows.PersistTaskOutcomeActivity)

	activities, closeActivities := buildAgentActivities()
	defer closeActivities()
	registrar := agentruntime.NewDefaultRegistrar(activities)
	registrar.RegisterWorkflows(&agentruntime.TemporalRuntime{Worker: w})
	registrar.RegisterActivities(&agentruntime.TemporalRuntime{Worker: w})

	go func() {
		if err := w.Run(worker.InterruptCh()); err != nil {
			log.Fatalf("temporal worker stopped with error: %v", err)
		}
	}()

	log.Printf("temporal worker started, endpoint=%s queue=%s", endpoint, taskQueue)
	log.Printf("goagent workflows: agent=%s, stream=%s",
		orchestration.AgentWorkflowName, orchestration.StreamWorkflowName)
	for {
		select {
		case <-ctx.Done():
			log.Println("task worker shutting down")
			return
		}
	}
}

func buildAgentActivities() (*orchestration.AgentActivities, func()) {
	l := logger.New("info")

	redisURL := buildRedisURLFromEnv()
	if redisURL == "" {
		log.Fatal("REDIS_HOST is required for GoAgent activities")
	}
	rdb, err := goagentredis.New(context.Background(), redisURL)
	if err != nil {
		log.Fatalf("failed to create GoAgent Redis client: %v", err)
	}
	sequencer := goagentstream.NewRedisSequencer(rdb)
	eventStore := goagentstream.NewRedisEventStore(rdb, sequencer)

	llmCfg := buildLLMConfigFromEnv()
	provider, err := webapi.NewBifrost(llmCfg)
	if err != nil {
		log.Fatalf("failed to create LLM provider: %v", err)
	}
	log.Printf("LLM provider configured with %d provider(s)", len(llmCfg.Providers))

	toolRegistry := toolkit.NewRegistry()
	toolPipeline := &agenttool.Pipeline{Executor: toolRegistry}
	toolExecutor := framework.NewToolPipeline(toolPipeline)

	walClient, err := newRedisClientFromEnv()
	if err != nil {
		log.Fatalf("failed to create WAL Redis client: %v", err)
	}
	wal := pipeline.NewWriteAheadLog(walClient)

	comp := compressor.New(compressor.Config{LLM: provider})

	agentUC := agentuc.New(provider, toolExecutor, wal, comp, toolRegistry, nil)

	return orchestration.NewAgentActivities(agentUC, eventStore, l), provider.Close
}

func buildRedisURLFromEnv() string {
	host := getenv("REDIS_HOST", "")
	port := getenv("REDIS_PORT", "6379")
	password := strings.TrimSpace(os.Getenv("REDIS_PASSWORD"))
	db := getenv("REDIS_DB", "0")
	if host == "" {
		return ""
	}
	if password != "" {
		return fmt.Sprintf("redis://:%s@%s:%s/%s", password, host, port, db)
	}
	return fmt.Sprintf("redis://%s:%s/%s", host, port, db)
}

func newRedisClientFromEnv() (goredis.Cmdable, error) {
	host := getenv("REDIS_HOST", "")
	if host == "" {
		return nil, fmt.Errorf("REDIS_HOST is required")
	}
	port := getenv("REDIS_PORT", "6379")
	password := strings.TrimSpace(os.Getenv("REDIS_PASSWORD"))
	dbStr := getenv("REDIS_DB", "0")
	db := 0
	fmt.Sscanf(dbStr, "%d", &db)

	client := goredis.NewClient(&goredis.Options{
		Addr:     host + ":" + port,
		Password: password,
		DB:       db,
	})
	if err := client.Ping(context.Background()).Err(); err != nil {
		return nil, err
	}
	return client, nil
}

func buildLLMConfigFromEnv() *webapi.BifrostConfig {
	provider := strings.TrimSpace(os.Getenv("LLM_PROVIDER"))
	apiKey := strings.TrimSpace(os.Getenv("LLM_API_KEY"))
	baseURL := strings.TrimSpace(os.Getenv("LLM_BASE_URL"))

	if provider == "" || apiKey == "" {
		log.Fatal("LLM_PROVIDER and LLM_API_KEY are required for GoAgent activities")
	}

	return &webapi.BifrostConfig{
		Providers: []webapi.ProviderEntry{
			{
				Provider: schemas.ModelProvider(provider),
				APIKey:   apiKey,
				BaseURL:  baseURL,
			},
		},
	}
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
