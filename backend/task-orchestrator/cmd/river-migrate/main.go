// Command river-migrate applies the River-owned PostgreSQL schema before the
// task-orchestrator starts processing durable export jobs.
package main

import (
	"context"
	"log"
	"os"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/riverqueue/river/riverdriver/riverpgxv5"
	"github.com/riverqueue/river/rivermigrate"
)

func main() {
	ctx := context.Background()
	databaseURL := strings.TrimSpace(os.Getenv("PG_URL"))
	if databaseURL == "" {
		log.Fatal("PG_URL is required")
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		log.Fatalf("connect PostgreSQL: %v", err)
	}
	defer pool.Close()
	migrator, err := rivermigrate.New(riverpgxv5.New(pool), nil)
	if err != nil {
		log.Fatalf("create River migrator: %v", err)
	}
	if _, err := migrator.Migrate(ctx, rivermigrate.DirectionUp, nil); err != nil {
		log.Fatalf("apply River migrations: %v", err)
	}
	log.Print("River migrations are current")
}
