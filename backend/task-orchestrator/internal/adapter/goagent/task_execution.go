package goagent

import (
	"context"
	"fmt"
	"strings"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
)

// TaskExecutionConfig declares the application-owned topology for one
// Kardcraft task. Backend selection remains at composition time and is never
// inferred from an HTTP request.
type TaskExecutionConfig struct {
	NodeID  string
	Backend agentos.BackendRef
}

// TaskExecution adapts Kardcraft's execution port to the generic AgentOS plan
// control plane. It is the only Kardcraft package that knows AgentOS plan
// types and external backend references.
type TaskExecution struct {
	runtime agentos.PlanRuntime
	routes  repo.TaskExecutionRouteStore
	config  TaskExecutionConfig
}

func NewTaskExecution(runtime agentos.PlanRuntime, routes repo.TaskExecutionRouteStore, config TaskExecutionConfig) (*TaskExecution, error) {
	if runtime == nil {
		return nil, fmt.Errorf("goagent plan runtime is required")
	}
	if routes == nil {
		return nil, fmt.Errorf("task execution route store is required")
	}
	config.NodeID = strings.TrimSpace(config.NodeID)
	config.Backend.Name = strings.TrimSpace(config.Backend.Name)
	if config.NodeID == "" || config.Backend.Kind == "" || config.Backend.Name == "" {
		return nil, fmt.Errorf("task execution node and backend are required")
	}

	return &TaskExecution{runtime: runtime, routes: routes, config: config}, nil
}

func (r *TaskExecution) StartTaskExecution(ctx context.Context, request usecase.TaskExecutionRequest) (usecase.TaskExecutionStatus, error) {
	if r == nil || r.runtime == nil {
		return usecase.TaskExecutionStatus{}, fmt.Errorf("goagent plan runtime is required")
	}
	if err := validateTaskExecutionRequest(request); err != nil {
		return usecase.TaskExecutionStatus{}, err
	}

	route := repo.TaskExecutionRoute{
		TaskID:       request.RunID,
		PlanID:       request.RunID,
		AccountID:    request.AccountID,
		ProjectID:    request.ProjectID,
		NodeID:       r.config.NodeID,
		BackendRunID: request.RunID,
	}
	if err := r.routes.BindTaskExecutionRoute(ctx, route); err != nil {
		return usecase.TaskExecutionStatus{}, err
	}

	status, err := r.runtime.StartPlan(ctx, &agentos.RunPlanSpec{
		PlanID:         route.PlanID,
		AccountID:      route.AccountID,
		ProjectID:      route.ProjectID,
		IdempotencyKey: request.IdempotencyKey,
		RequestedAt:    request.RequestedAt,
		Nodes: []agentos.PlanNodeSpec{{
			NodeID: route.NodeID,
			Run: agentos.RunSpec{
				RunID:          route.BackendRunID,
				ThreadID:       request.ThreadID,
				AccountID:      request.AccountID,
				ProjectID:      request.ProjectID,
				AgentID:        request.AgentID,
				ModelRef:       request.ModelRef,
				SystemPrompt:   request.SystemPrompt,
				UserMessage:    request.UserMessage,
				IdempotencyKey: request.IdempotencyKey,
				RequestedAt:    request.RequestedAt,
				Metadata:       request.Metadata,
				Backend:        r.config.Backend,
				Input:          request.Input,
			},
		}},
	})
	if err != nil {
		return usecase.TaskExecutionStatus{}, err
	}

	return taskExecutionStatus(route, status), nil
}

func (r *TaskExecution) GetTaskExecutionStatus(ctx context.Context, taskID string) (usecase.TaskExecutionStatus, error) {
	route, err := r.route(ctx, taskID)
	if err != nil {
		return usecase.TaskExecutionStatus{}, err
	}
	status, err := r.runtime.StatusPlan(ctx, planRef(route))
	if err != nil {
		return usecase.TaskExecutionStatus{}, err
	}

	return taskExecutionStatus(route, status), nil
}

func (r *TaskExecution) SignalTaskExecution(ctx context.Context, taskID string, signal usecase.TaskExecutionSignal) error {
	route, err := r.route(ctx, taskID)
	if err != nil {
		return err
	}

	return r.runtime.SignalPlan(ctx, planRef(route), &agentoscore.Signal{
		Type:           agentoscore.SignalType(signal.Type),
		IdempotencyKey: signal.IdempotencyKey,
		ActorID:        signal.ActorID,
		Payload:        signal.Payload,
		SentAt:         signal.SentAt,
	})
}

func (r *TaskExecution) ControlTaskExecution(ctx context.Context, taskID string, control usecase.TaskExecutionControl) error {
	route, err := r.route(ctx, taskID)
	if err != nil {
		return err
	}

	return r.runtime.ControlPlan(ctx, planRef(route), &agentoscore.ControlRequest{
		Operation:      agentoscore.ControlOperation(control.Operation),
		IdempotencyKey: control.IdempotencyKey,
		RequestedAt:    control.RequestedAt,
		ActorID:        control.ActorID,
		Metadata:       control.Metadata,
	})
}

func (r *TaskExecution) SubscribeTaskExecution(ctx context.Context, scope usecase.TaskExecutionEventScope) (usecase.TaskExecutionSubscription, error) {
	route, err := r.route(ctx, scope.TaskID)
	if err != nil {
		return nil, err
	}
	subscription, err := r.runtime.SubscribePlan(ctx, &agentos.PlanStreamScope{
		PlanID:        route.PlanID,
		AccountID:     route.AccountID,
		ProjectID:     route.ProjectID,
		NodeID:        route.NodeID,
		RunID:         route.BackendRunID,
		AfterSequence: scope.AfterSequence,
	})
	if err != nil {
		return nil, err
	}

	return &taskExecutionSubscription{sub: subscription}, nil
}

func (r *TaskExecution) IngestTaskExecutionEvent(ctx context.Context, incoming usecase.ExternalTaskExecutionEvent) (usecase.TaskExecutionEvent, error) {
	if r == nil || r.runtime == nil {
		return usecase.TaskExecutionEvent{}, fmt.Errorf("goagent plan runtime is required")
	}
	if err := validateExternalTaskExecutionEvent(incoming); err != nil {
		return usecase.TaskExecutionEvent{}, err
	}
	route, found, err := r.routes.GetTaskExecutionRouteByBackendRun(ctx, strings.TrimSpace(incoming.RunID))
	if err != nil {
		return usecase.TaskExecutionEvent{}, err
	}
	if !found {
		return usecase.TaskExecutionEvent{}, fmt.Errorf("task execution route not found for backend run: %s", incoming.RunID)
	}
	if threadID := strings.TrimSpace(incoming.ThreadID); threadID != "" && threadID != route.ProjectID {
		return usecase.TaskExecutionEvent{}, fmt.Errorf("external task execution event thread does not match execution route")
	}

	stored, err := r.runtime.IngestExternalPlanEvent(ctx, &agentos.ExternalPlanEvent{
		Plan:   planRef(route),
		NodeID: route.NodeID,
		Event: agentoscore.Event{
			EventID:   strings.TrimSpace(incoming.EventID),
			EventType: agentoscore.EventType(strings.TrimSpace(incoming.EventType)),
			RunID:     route.BackendRunID,
			ThreadID:  route.ProjectID,
			Sequence:  incoming.Sequence,
			Timestamp: incoming.Timestamp,
			Source:    strings.TrimSpace(incoming.Source),
			Payload:   incoming.Payload,
		},
	})
	if err != nil {
		return usecase.TaskExecutionEvent{}, err
	}

	return taskExecutionEvent(stored), nil
}

func (r *TaskExecution) Close() error {
	if r == nil || r.runtime == nil {
		return nil
	}
	closer, ok := r.runtime.(interface{ Close() error })
	if !ok {
		return nil
	}

	return closer.Close()
}

func (r *TaskExecution) route(ctx context.Context, taskID string) (repo.TaskExecutionRoute, error) {
	if r == nil || r.routes == nil {
		return repo.TaskExecutionRoute{}, fmt.Errorf("task execution route store is required")
	}
	route, found, err := r.routes.GetTaskExecutionRoute(ctx, strings.TrimSpace(taskID))
	if err != nil {
		return repo.TaskExecutionRoute{}, err
	}
	if !found {
		return repo.TaskExecutionRoute{}, fmt.Errorf("task execution route not found: %s", taskID)
	}

	return route, nil
}

func validateTaskExecutionRequest(request usecase.TaskExecutionRequest) error {
	if strings.TrimSpace(request.RunID) == "" || strings.TrimSpace(request.ThreadID) == "" || strings.TrimSpace(request.AccountID) == "" || strings.TrimSpace(request.ProjectID) == "" || strings.TrimSpace(request.IdempotencyKey) == "" {
		return fmt.Errorf("task execution requires run, thread, account, project, and idempotency ids")
	}

	return nil
}

func validateExternalTaskExecutionEvent(event usecase.ExternalTaskExecutionEvent) error {
	if strings.TrimSpace(event.EventID) == "" || strings.TrimSpace(event.RunID) == "" || strings.TrimSpace(event.EventType) == "" || strings.TrimSpace(event.Source) == "" || event.Sequence <= 0 || event.Timestamp.IsZero() {
		return fmt.Errorf("external task execution event requires id, run, type, source, positive sequence, and timestamp")
	}

	return nil
}

func planRef(route repo.TaskExecutionRoute) agentos.PlanRef {
	return agentos.PlanRef{PlanID: route.PlanID, AccountID: route.AccountID, ProjectID: route.ProjectID}
}

func taskExecutionStatus(route repo.TaskExecutionRoute, status agentos.RunPlanStatus) usecase.TaskExecutionStatus {
	return usecase.TaskExecutionStatus{
		TaskID:         route.TaskID,
		PlanID:         route.PlanID,
		RunID:          route.BackendRunID,
		LifecycleState: string(status.LifecycleState),
		Reason:         status.Reason,
		UpdatedAt:      status.UpdatedAt,
	}
}

func taskExecutionEvent(event agentos.PlanEvent) usecase.TaskExecutionEvent {
	return usecase.TaskExecutionEvent{
		EventID:   event.EventID,
		EventType: string(event.EventType),
		RunID:     event.RunID,
		ThreadID:  event.ThreadID,
		Sequence:  event.Sequence,
		Timestamp: event.Timestamp,
		Payload:   event.Payload,
	}
}

type taskExecutionSubscription struct {
	sub agentoscore.Subscription
}

func (s *taskExecutionSubscription) Events() <-chan usecase.TaskExecutionEvent {
	out := make(chan usecase.TaskExecutionEvent)
	go func() {
		defer close(out)
		for event := range s.sub.Events() {
			out <- taskExecutionEvent(agentos.PlanEvent{Event: event})
		}
	}()

	return out
}

func (s *taskExecutionSubscription) Close() error {
	if s == nil || s.sub == nil {
		return nil
	}

	return s.sub.Close()
}
