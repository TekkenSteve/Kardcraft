package main

import (
	"context"
	"log"
	"os/signal"
	"syscall"
	"time"

	httpserver "task-orchestrator/internal/infrastructure/http"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	srv := httpserver.NewServer(httpserver.DefaultPortFromEnv())
	if err := srv.Start(ctx); err != nil {
		log.Fatalf("failed to start orchestrator: %v", err)
	}
	log.Printf("task orchestrator listening on %s", srv.Addr())

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("graceful shutdown error: %v", err)
	}
}
