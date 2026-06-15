package goagent

import (
	"context"
	"fmt"

	"github.com/TekkenSteve/GoAgent/agentos"

	"task-orchestrator/internal/usecase"
)

type Runtime struct {
	runtime agentos.Runtime
}

func NewRuntime(runtime agentos.Runtime) *Runtime {
	return &Runtime{runtime: runtime}
}

func (r *Runtime) StartAgentRun(ctx context.Context, req usecase.AgentRunRequest) (usecase.AgentRunStatus, error) {
	if r == nil || r.runtime == nil {
		return usecase.AgentRunStatus{}, fmt.Errorf("goagent runtime is required")
	}
	status, err := r.runtime.Start(ctx, agentos.RunSpec{
		RunID:          req.RunID,
		ThreadID:       req.ThreadID,
		AccountID:      req.AccountID,
		ProjectID:      req.ProjectID,
		AgentID:        req.AgentID,
		ModelRef:       req.ModelRef,
		SystemPrompt:   req.SystemPrompt,
		UserMessage:    req.UserMessage,
		IdempotencyKey: req.IdempotencyKey,
		RequestedAt:    req.RequestedAt,
		Metadata:       req.Metadata,
	})
	if err != nil {
		return usecase.AgentRunStatus{}, err
	}
	return agentRunStatusFromAgentOS(status), nil
}

func (r *Runtime) ControlAgentRun(ctx context.Context, runID string, op usecase.AgentControlOperation) error {
	if r == nil || r.runtime == nil {
		return fmt.Errorf("goagent runtime is required")
	}
	return r.runtime.Control(ctx, runID, agentos.ControlOperation(op))
}

func (r *Runtime) SubscribeAgentEvents(ctx context.Context, scope usecase.AgentEventScope) (usecase.AgentEventSubscription, error) {
	if r == nil || r.runtime == nil {
		return nil, fmt.Errorf("goagent runtime is required")
	}
	sub, err := r.runtime.Subscribe(ctx, agentos.StreamScope{
		RunID:         scope.RunID,
		ThreadID:      scope.ThreadID,
		AfterSequence: scope.AfterSequence,
	})
	if err != nil {
		return nil, err
	}
	return &subscription{sub: sub}, nil
}

func (r *Runtime) Close() error {
	if r == nil || r.runtime == nil {
		return nil
	}
	return r.runtime.Close()
}

func agentRunStatusFromAgentOS(status agentos.RunStatus) usecase.AgentRunStatus {
	return usecase.AgentRunStatus{
		RunID:          status.RunID,
		LifecycleState: status.LifecycleState,
		Step:           status.Step,
		Reason:         status.Reason,
		UpdatedAt:      status.UpdatedAt,
	}
}

type subscription struct {
	sub agentos.Subscription
}

func (s *subscription) Events() <-chan usecase.AgentRuntimeEvent {
	out := make(chan usecase.AgentRuntimeEvent)
	go func() {
		defer close(out)
		for event := range s.sub.Events() {
			out <- usecase.AgentRuntimeEvent{
				EventID:   event.EventID,
				EventType: event.EventType,
				RunID:     event.RunID,
				ThreadID:  event.ThreadID,
				Sequence:  event.Sequence,
				Timestamp: event.Timestamp,
				Payload:   event.Payload,
			}
		}
	}()
	return out
}

func (s *subscription) Close() error {
	if s == nil || s.sub == nil {
		return nil
	}
	return s.sub.Close()
}
