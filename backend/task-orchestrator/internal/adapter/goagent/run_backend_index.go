package goagent

import (
	"context"
	"fmt"
	"strings"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"

	"task-orchestrator/internal/repo"
)

type RunBackendIndex struct {
	store repo.AgentRunRouteStore
}

func NewRunBackendIndex(store repo.AgentRunRouteStore) *RunBackendIndex {
	return &RunBackendIndex{store: store}
}

func (i *RunBackendIndex) Bind(ctx context.Context, spec *agentos.RunSpec, status *agentos.RunStatus) error {
	if i == nil || i.store == nil {
		return fmt.Errorf("agentos run route store is required")
	}
	return i.store.BindAgentRunRoute(ctx, routeFromRunSpec("", "", spec, status))
}

func (i *RunBackendIndex) BindPlanNode(ctx context.Context, planID, nodeID string, spec *agentos.RunSpec, status *agentos.RunStatus) error {
	if i == nil || i.store == nil {
		return fmt.Errorf("agentos run route store is required")
	}
	if strings.TrimSpace(planID) == "" {
		return fmt.Errorf("%w: plan id is required", agentoscore.ErrInvalidRunPlan)
	}
	if strings.TrimSpace(nodeID) == "" {
		return fmt.Errorf("%w: node id is required", agentoscore.ErrInvalidRunPlan)
	}
	return i.store.BindAgentRunRoute(ctx, routeFromRunSpec(planID, nodeID, spec, status))
}

func (i *RunBackendIndex) GetRunBackend(ctx context.Context, runID string) (agentos.RunBackendOwnership, bool, error) {
	if i == nil || i.store == nil {
		return agentos.RunBackendOwnership{}, false, fmt.Errorf("agentos run route store is required")
	}
	route, ok, err := i.store.GetAgentRunRoute(ctx, runID)
	if err != nil || !ok {
		return agentos.RunBackendOwnership{}, ok, err
	}
	return ownershipFromRoute(route), true, nil
}

func (i *RunBackendIndex) Resolve(ctx context.Context, runID string) (agentos.BackendRef, error) {
	if i == nil || i.store == nil {
		return agentos.BackendRef{}, fmt.Errorf("agentos run route store is required")
	}
	route, ok, err := i.store.ResolveAgentRunRoute(ctx, runID)
	if err != nil {
		return agentos.BackendRef{}, err
	}
	if !ok {
		return agentos.BackendRef{}, fmt.Errorf("%w: %s", agentoscore.ErrRunRouteNotFound, runID)
	}
	return agentos.BackendRef{
		Kind: agentos.BackendKind(route.BackendKind),
		Name: route.BackendName,
	}, nil
}

func routeFromRunSpec(planID, nodeID string, spec *agentos.RunSpec, status *agentos.RunStatus) repo.AgentRunRoute {
	var route repo.AgentRunRoute
	if spec != nil {
		route.RunID = strings.TrimSpace(spec.RunID)
		route.ThreadID = strings.TrimSpace(spec.ThreadID)
		route.AccountID = strings.TrimSpace(spec.AccountID)
		route.ProjectID = strings.TrimSpace(spec.ProjectID)
		route.BackendKind = strings.TrimSpace(string(spec.Backend.Kind))
		route.BackendName = strings.TrimSpace(spec.Backend.Name)
		route.IdempotencyKey = strings.TrimSpace(spec.IdempotencyKey)
	}
	if status != nil {
		if runID := strings.TrimSpace(status.RunID); runID != "" {
			route.RunID = runID
		}
		route.LifecycleState = strings.TrimSpace(status.LifecycleState)
	}
	if route.LifecycleState == "" {
		route.LifecycleState = "created"
	}
	route.PlanID = strings.TrimSpace(planID)
	route.NodeID = strings.TrimSpace(nodeID)
	return route
}

func ownershipFromRoute(route repo.AgentRunRoute) agentos.RunBackendOwnership {
	return agentos.RunBackendOwnership{
		RunID:          route.RunID,
		PlanID:         route.PlanID,
		NodeID:         route.NodeID,
		ThreadID:       route.ThreadID,
		AccountID:      route.AccountID,
		ProjectID:      route.ProjectID,
		Backend:        agentos.BackendRef{Kind: agentos.BackendKind(route.BackendKind), Name: route.BackendName},
		IdempotencyKey: route.IdempotencyKey,
		LifecycleState: route.LifecycleState,
		CreatedAt:      route.CreatedAt,
		UpdatedAt:      route.UpdatedAt,
	}
}
