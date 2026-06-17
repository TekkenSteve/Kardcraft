package goagent

import (
	"context"
	"fmt"
	"strings"

	"github.com/TekkenSteve/GoAgent/agentos"

	"task-orchestrator/internal/repo"
)

type RunBackendIndex struct {
	store repo.AgentRunRouteStore
}

func NewRunBackendIndex(store repo.AgentRunRouteStore) *RunBackendIndex {
	return &RunBackendIndex{store: store}
}

func (i *RunBackendIndex) Bind(ctx context.Context, spec agentos.RunSpec) error {
	if i == nil || i.store == nil {
		return fmt.Errorf("agentos run route store is required")
	}
	runID := strings.TrimSpace(spec.RunID)
	if runID == "" {
		return fmt.Errorf("%w: run id is required", agentos.ErrInvalidRunSpec)
	}
	if strings.TrimSpace(string(spec.Backend.Kind)) == "" || strings.TrimSpace(spec.Backend.Name) == "" {
		return fmt.Errorf("%w: kind and name are required", agentos.ErrInvalidBackendRef)
	}
	return i.store.BindAgentRunRoute(ctx, repo.AgentRunRoute{
		RunID:          runID,
		ThreadID:       spec.ThreadID,
		AccountID:      spec.AccountID,
		ProjectID:      spec.ProjectID,
		BackendKind:    string(spec.Backend.Kind),
		BackendName:    spec.Backend.Name,
		LifecycleState: "created",
	})
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
		return agentos.BackendRef{}, fmt.Errorf("%w: %s", agentos.ErrRunRouteNotFound, runID)
	}
	return agentos.BackendRef{
		Kind: agentos.BackendKind(route.BackendKind),
		Name: route.BackendName,
	}, nil
}
