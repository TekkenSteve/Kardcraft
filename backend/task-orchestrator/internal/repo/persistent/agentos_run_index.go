package persistent

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"task-orchestrator/internal/repo"
)

type AgentOSRunIndex struct {
	store *SessionStore
}

func NewAgentOSRunIndex(store *SessionStore) *AgentOSRunIndex {
	return &AgentOSRunIndex{store: store}
}

func (i *AgentOSRunIndex) BindAgentRunRoute(ctx context.Context, route repo.AgentRunRoute) error {
	if i == nil || i.store == nil || i.store.pg == nil {
		return fmt.Errorf("agentos run index postgres unavailable")
	}
	runID := strings.TrimSpace(route.RunID)
	if runID == "" {
		return fmt.Errorf("agentos run route requires run id")
	}
	if strings.TrimSpace(route.BackendKind) == "" || strings.TrimSpace(route.BackendName) == "" {
		return fmt.Errorf("agentos run route requires backend kind and name")
	}
	lifecycleState := strings.TrimSpace(route.LifecycleState)
	if lifecycleState == "" {
		lifecycleState = "created"
	}
	_, err := i.store.pg.Exec(ctx, `
		INSERT INTO agentos_runs (
			run_id,
			thread_id,
			account_id,
			project_id,
			backend_kind,
			backend_name,
			lifecycle_state,
			updated_at
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
		ON CONFLICT (run_id) DO UPDATE SET
			thread_id = EXCLUDED.thread_id,
			account_id = EXCLUDED.account_id,
			project_id = EXCLUDED.project_id,
			backend_kind = EXCLUDED.backend_kind,
			backend_name = EXCLUDED.backend_name,
			lifecycle_state = EXCLUDED.lifecycle_state,
			updated_at = NOW()
	`, runID, route.ThreadID, route.AccountID, route.ProjectID, route.BackendKind, route.BackendName, lifecycleState)
	if err != nil {
		return fmt.Errorf("bind agentos run backend: %w", err)
	}
	return nil
}

func (i *AgentOSRunIndex) ResolveAgentRunRoute(ctx context.Context, runID string) (repo.AgentRunRoute, bool, error) {
	if i == nil || i.store == nil || i.store.pg == nil {
		return repo.AgentRunRoute{}, false, fmt.Errorf("agentos run index postgres unavailable")
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		return repo.AgentRunRoute{}, false, fmt.Errorf("agentos run route requires run id")
	}
	var kind string
	var name string
	err := i.store.pg.QueryRow(ctx, `
		SELECT backend_kind, backend_name
		FROM agentos_runs
		WHERE run_id = $1
	`, runID).Scan(&kind, &name)
	if err != nil {
		if err == pgx.ErrNoRows {
			return repo.AgentRunRoute{}, false, nil
		}
		return repo.AgentRunRoute{}, false, fmt.Errorf("resolve agentos run backend: %w", err)
	}
	return repo.AgentRunRoute{
		RunID:       runID,
		BackendKind: kind,
		BackendName: name,
	}, true, nil
}
