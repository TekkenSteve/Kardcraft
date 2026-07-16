package persistent

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"task-orchestrator/internal/repo"
)

// TaskExecutionIndex maps Kardcraft tasks to their AgentOS plan identity.
// The mapping is written by the command use case before a task is observable
// to runtime reads, so HTTP handlers never derive tenancy from request data.
type TaskExecutionIndex struct {
	store *SessionStore
}

func NewTaskExecutionIndex(store *SessionStore) *TaskExecutionIndex {
	return &TaskExecutionIndex{store: store}
}

func (i *TaskExecutionIndex) BindTaskExecutionRoute(ctx context.Context, route repo.TaskExecutionRoute) error {
	if i == nil || i.store == nil || i.store.pg == nil {
		return fmt.Errorf("task execution index postgres unavailable")
	}
	route = normalizeTaskExecutionRoute(route)
	if err := validateTaskExecutionRoute(route); err != nil {
		return err
	}

	command, err := i.store.pg.Exec(ctx, `
		INSERT INTO kc_task_execution (task_id, plan_id, account_id, project_id, node_id, backend_run_id)
		VALUES ($1, $2, $3, $4, $5, $6)
		ON CONFLICT (task_id) DO NOTHING
	`, route.TaskID, route.PlanID, route.AccountID, route.ProjectID, route.NodeID, route.BackendRunID)
	if err != nil {
		return fmt.Errorf("bind task execution route: %w", err)
	}
	if command.RowsAffected() == 1 {
		return nil
	}

	existing, found, err := i.GetTaskExecutionRoute(ctx, route.TaskID)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("task execution route conflict left no route: %s", route.TaskID)
	}
	if existing != route {
		return fmt.Errorf("task execution route already belongs to a different plan")
	}

	return nil
}

func (i *TaskExecutionIndex) GetTaskExecutionRoute(ctx context.Context, taskID string) (repo.TaskExecutionRoute, bool, error) {
	return i.getTaskExecutionRoute(ctx, "task_id", taskID)
}

func (i *TaskExecutionIndex) GetTaskExecutionRouteByBackendRun(ctx context.Context, backendRunID string) (repo.TaskExecutionRoute, bool, error) {
	return i.getTaskExecutionRoute(ctx, "backend_run_id", backendRunID)
}

func (i *TaskExecutionIndex) ListActiveTaskExecutionRoutes(ctx context.Context) ([]repo.TaskExecutionRoute, error) {
	if i == nil || i.store == nil || i.store.pg == nil {
		return nil, fmt.Errorf("task execution index postgres unavailable")
	}
	rows, err := i.store.pg.Query(ctx, `
		SELECT execution.task_id, execution.plan_id, execution.account_id, execution.project_id, execution.node_id, execution.backend_run_id
		FROM kc_task_execution AS execution
		JOIN kc_tasks AS task ON task.task_id = execution.task_id
		WHERE LOWER(COALESCE(task.status, '')) IN ('pending', 'queued', 'running', 'paused')
		ORDER BY execution.created_at
	`)
	if err != nil {
		return nil, fmt.Errorf("list active task execution routes: %w", err)
	}
	defer rows.Close()

	routes := make([]repo.TaskExecutionRoute, 0)
	for rows.Next() {
		var route repo.TaskExecutionRoute
		if err := rows.Scan(&route.TaskID, &route.PlanID, &route.AccountID, &route.ProjectID, &route.NodeID, &route.BackendRunID); err != nil {
			return nil, fmt.Errorf("scan active task execution route: %w", err)
		}
		routes = append(routes, route)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate active task execution routes: %w", err)
	}

	return routes, nil
}

func (i *TaskExecutionIndex) getTaskExecutionRoute(ctx context.Context, column, value string) (repo.TaskExecutionRoute, bool, error) {
	if i == nil || i.store == nil || i.store.pg == nil {
		return repo.TaskExecutionRoute{}, false, fmt.Errorf("task execution index postgres unavailable")
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return repo.TaskExecutionRoute{}, false, fmt.Errorf("task execution route lookup value is required")
	}
	if column != "task_id" && column != "backend_run_id" {
		return repo.TaskExecutionRoute{}, false, fmt.Errorf("unsupported task execution route lookup")
	}

	var route repo.TaskExecutionRoute
	err := i.store.pg.QueryRow(ctx, `
		SELECT task_id, plan_id, account_id, project_id, node_id, backend_run_id
		FROM kc_task_execution
		WHERE `+column+` = $1
	`, value).Scan(
		&route.TaskID,
		&route.PlanID,
		&route.AccountID,
		&route.ProjectID,
		&route.NodeID,
		&route.BackendRunID,
	)
	if err == pgx.ErrNoRows {
		return repo.TaskExecutionRoute{}, false, nil
	}
	if err != nil {
		return repo.TaskExecutionRoute{}, false, fmt.Errorf("get task execution route: %w", err)
	}

	return route, true, nil
}

func normalizeTaskExecutionRoute(route repo.TaskExecutionRoute) repo.TaskExecutionRoute {
	route.TaskID = strings.TrimSpace(route.TaskID)
	route.PlanID = strings.TrimSpace(route.PlanID)
	route.AccountID = strings.TrimSpace(route.AccountID)
	route.ProjectID = strings.TrimSpace(route.ProjectID)
	route.NodeID = strings.TrimSpace(route.NodeID)
	route.BackendRunID = strings.TrimSpace(route.BackendRunID)
	return route
}

func validateTaskExecutionRoute(route repo.TaskExecutionRoute) error {
	if route.TaskID == "" || route.PlanID == "" || route.AccountID == "" || route.ProjectID == "" || route.NodeID == "" || route.BackendRunID == "" {
		return fmt.Errorf("task execution route requires task, plan, account, project, node, and backend run ids")
	}

	return nil
}
