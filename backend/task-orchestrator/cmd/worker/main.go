package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	gosdk "go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"

	"github.com/TekkenSteve/GoAgent/agentfw/orchestration"
	"task-orchestrator/internal/repo/persistence"
	"task-orchestrator/internal/runtime/temporal/workflows"
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
	sessionStore := persistence.NewSessionStore(context.Background(), persistence.SessionStoreConfigFromEnv())
	workflows.ConfigureTaskPersistenceStore(sessionStore)
	w.RegisterActivity(workflows.PersistTaskOutcomeActivity)

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

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
