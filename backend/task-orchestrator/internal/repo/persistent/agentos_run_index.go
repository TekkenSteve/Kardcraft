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
	route = normalizeAgentRunRoute(route)
	if err := validateAgentRunRoute(route); err != nil {
		return err
	}
	if route.IdempotencyKey != "" {
		existing, ok, err := i.resolveAgentRunRouteByIdempotencyKey(ctx, route)
		if err != nil {
			return err
		}
		if ok {
			if err := ensureSameAgentRunRoute(existing, route); err != nil {
				return err
			}
			return i.updateAgentRunRouteLifecycle(ctx, existing.RunID, route.LifecycleState)
		}
	}
	tag, err := i.store.pg.Exec(ctx, `
		INSERT INTO agentos_runs (
			run_id,
			plan_id,
			node_id,
			thread_id,
			account_id,
			project_id,
			backend_kind,
			backend_name,
			idempotency_key,
			lifecycle_state,
			updated_at
		)
		VALUES ($1, NULLIF($2, ''), NULLIF($3, ''), $4, $5, $6, $7, $8, $9, $10, NOW())
		ON CONFLICT (run_id) DO NOTHING
	`, route.RunID, route.PlanID, route.NodeID, route.ThreadID, route.AccountID, route.ProjectID, route.BackendKind, route.BackendName, route.IdempotencyKey, route.LifecycleState)
	if err != nil {
		return fmt.Errorf("bind agentos run backend: %w", err)
	}
	if tag.RowsAffected() == 0 {
		existing, ok, err := i.GetAgentRunRoute(ctx, route.RunID)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("agentos run route conflict left no ownership record: %s", route.RunID)
		}
		if err := ensureSameAgentRunRoute(existing, route); err != nil {
			return err
		}
		return i.updateAgentRunRouteLifecycle(ctx, existing.RunID, route.LifecycleState)
	}
	return nil
}

func (i *AgentOSRunIndex) ResolveAgentRunRoute(ctx context.Context, runID string) (repo.AgentRunRoute, bool, error) {
	route, ok, err := i.GetAgentRunRoute(ctx, runID)
	if err != nil || !ok {
		return route, ok, err
	}
	return repo.AgentRunRoute{
		RunID:       route.RunID,
		BackendKind: route.BackendKind,
		BackendName: route.BackendName,
	}, true, nil
}

func (i *AgentOSRunIndex) GetAgentRunRoute(ctx context.Context, runID string) (repo.AgentRunRoute, bool, error) {
	if i == nil || i.store == nil || i.store.pg == nil {
		return repo.AgentRunRoute{}, false, fmt.Errorf("agentos run index postgres unavailable")
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		return repo.AgentRunRoute{}, false, fmt.Errorf("agentos run route requires run id")
	}
	route, ok, err := scanAgentRunRoute(i.store.pg.QueryRow(ctx, `
		SELECT
			run_id,
			COALESCE(plan_id, '') AS plan_id,
			COALESCE(node_id, '') AS node_id,
			thread_id,
			account_id,
			project_id,
			backend_kind,
			backend_name,
			COALESCE(idempotency_key, '') AS idempotency_key,
			lifecycle_state,
			created_at,
			updated_at
		FROM agentos_runs
		WHERE run_id = $1
	`, runID))
	if err != nil {
		return repo.AgentRunRoute{}, false, fmt.Errorf("resolve agentos run backend: %w", err)
	}
	return route, ok, nil
}

func (i *AgentOSRunIndex) resolveAgentRunRouteByIdempotencyKey(ctx context.Context, route repo.AgentRunRoute) (repo.AgentRunRoute, bool, error) {
	found, ok, err := scanAgentRunRoute(i.store.pg.QueryRow(ctx, `
		SELECT
			run_id,
			COALESCE(plan_id, '') AS plan_id,
			COALESCE(node_id, '') AS node_id,
			thread_id,
			account_id,
			project_id,
			backend_kind,
			backend_name,
			COALESCE(idempotency_key, '') AS idempotency_key,
			lifecycle_state,
			created_at,
			updated_at
		FROM agentos_runs
		WHERE account_id = $1
		  AND project_id = $2
		  AND idempotency_key = $3
	`, route.AccountID, route.ProjectID, route.IdempotencyKey))
	if err != nil {
		return repo.AgentRunRoute{}, false, fmt.Errorf("resolve agentos run backend by idempotency key: %w", err)
	}
	return found, ok, nil
}

func (i *AgentOSRunIndex) updateAgentRunRouteLifecycle(ctx context.Context, runID, lifecycleState string) error {
	_, err := i.store.pg.Exec(ctx, `
		UPDATE agentos_runs
		SET lifecycle_state = $2,
			updated_at = NOW()
		WHERE run_id = $1
	`, runID, lifecycleState)
	if err != nil {
		return fmt.Errorf("update agentos run lifecycle: %w", err)
	}
	return nil
}

func scanAgentRunRoute(row pgx.Row) (repo.AgentRunRoute, bool, error) {
	var route repo.AgentRunRoute
	err := row.Scan(
		&route.RunID,
		&route.PlanID,
		&route.NodeID,
		&route.ThreadID,
		&route.AccountID,
		&route.ProjectID,
		&route.BackendKind,
		&route.BackendName,
		&route.IdempotencyKey,
		&route.LifecycleState,
		&route.CreatedAt,
		&route.UpdatedAt,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return repo.AgentRunRoute{}, false, nil
		}
		return repo.AgentRunRoute{}, false, err
	}
	return route, true, nil
}

func normalizeAgentRunRoute(route repo.AgentRunRoute) repo.AgentRunRoute {
	route.RunID = strings.TrimSpace(route.RunID)
	route.PlanID = strings.TrimSpace(route.PlanID)
	route.NodeID = strings.TrimSpace(route.NodeID)
	route.ThreadID = strings.TrimSpace(route.ThreadID)
	route.AccountID = strings.TrimSpace(route.AccountID)
	route.ProjectID = strings.TrimSpace(route.ProjectID)
	route.BackendKind = strings.TrimSpace(route.BackendKind)
	route.BackendName = strings.TrimSpace(route.BackendName)
	route.IdempotencyKey = strings.TrimSpace(route.IdempotencyKey)
	route.LifecycleState = strings.TrimSpace(route.LifecycleState)
	if route.LifecycleState == "" {
		route.LifecycleState = "created"
	}
	return route
}

func validateAgentRunRoute(route repo.AgentRunRoute) error {
	if route.RunID == "" {
		return fmt.Errorf("agentos run route requires run id")
	}
	if route.AccountID == "" {
		return fmt.Errorf("agentos run route requires account id")
	}
	if route.ProjectID == "" {
		return fmt.Errorf("agentos run route requires project id")
	}
	if route.BackendKind == "" || route.BackendName == "" {
		return fmt.Errorf("agentos run route requires backend kind and name")
	}
	if route.IdempotencyKey == "" {
		return fmt.Errorf("agentos run route requires idempotency key")
	}
	if (route.PlanID == "") != (route.NodeID == "") {
		return fmt.Errorf("agentos run route plan id and node id must be provided together")
	}
	return nil
}

func ensureSameAgentRunRoute(existing, requested repo.AgentRunRoute) error {
	existing = normalizeAgentRunRoute(existing)
	requested = normalizeAgentRunRoute(requested)
	if existing.RunID != requested.RunID {
		return fmt.Errorf("agentos run idempotency key belongs to run %q, got %q", existing.RunID, requested.RunID)
	}
	if existing.PlanID != requested.PlanID || existing.NodeID != requested.NodeID {
		return fmt.Errorf("agentos run %q idempotency key was reused for a different plan node", requested.RunID)
	}
	if existing.ThreadID != requested.ThreadID || existing.AccountID != requested.AccountID || existing.ProjectID != requested.ProjectID {
		return fmt.Errorf("agentos run %q idempotency key was reused for a different scope", requested.RunID)
	}
	if existing.BackendKind != requested.BackendKind || existing.BackendName != requested.BackendName {
		return fmt.Errorf("agentos run %q idempotency key was reused for a different backend", requested.RunID)
	}
	if existing.IdempotencyKey != "" && requested.IdempotencyKey != "" && existing.IdempotencyKey != requested.IdempotencyKey {
		return fmt.Errorf("agentos run %q was already bound with a different idempotency key", requested.RunID)
	}
	return nil
}
