package goagent

import (
	"context"
	"fmt"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"

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
	status, err := r.runtime.Start(ctx, &agentos.RunSpec{
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
		Backend: agentos.BackendRef{
			Kind: agentos.BackendKind(req.Backend.Kind),
			Name: req.Backend.Name,
		},
		Input: req.Input,
	})
	if err != nil {
		return usecase.AgentRunStatus{}, err
	}
	return agentRunStatusFromAgentOS(status), nil
}

func (r *Runtime) SignalAgentRun(ctx context.Context, runID string, signal usecase.AgentSignal) error {
	if r == nil || r.runtime == nil {
		return fmt.Errorf("goagent runtime is required")
	}
	return r.runtime.Signal(ctx, runID, &agentoscore.Signal{
		Type:           agentoscore.SignalType(signal.Type),
		IdempotencyKey: signal.IdempotencyKey,
		Payload:        signal.Payload,
		SentAt:         signal.SentAt,
	})
}

func (r *Runtime) ControlAgentRun(ctx context.Context, runID string, control usecase.AgentControlRequest) error {
	if r == nil || r.runtime == nil {
		return fmt.Errorf("goagent runtime is required")
	}
	return r.runtime.Control(ctx, runID, &agentoscore.ControlRequest{
		Operation:      agentoscore.ControlOperation(control.Operation),
		IdempotencyKey: control.IdempotencyKey,
		RequestedAt:    control.RequestedAt,
		ActorID:        control.ActorID,
		Metadata:       control.Metadata,
	})
}

func (r *Runtime) SubscribeAgentEvents(ctx context.Context, scope usecase.AgentEventScope) (usecase.AgentEventSubscription, error) {
	if r == nil || r.runtime == nil {
		return nil, fmt.Errorf("goagent runtime is required")
	}
	sub, err := r.runtime.Subscribe(ctx, agentoscore.StreamScope{
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
	var progress *usecase.AgentRunProgress
	if status.Progress != nil {
		progress = &usecase.AgentRunProgress{
			Current: status.Progress.Current,
			Total:   status.Progress.Total,
			Label:   status.Progress.Label,
		}
	}
	return usecase.AgentRunStatus{
		RunID:          status.RunID,
		LifecycleState: status.LifecycleState,
		Progress:       progress,
		Reason:         status.Reason,
		UpdatedAt:      status.UpdatedAt,
	}
}

type subscription struct {
	sub agentoscore.Subscription
}

func (s *subscription) Events() <-chan usecase.AgentRuntimeEvent {
	out := make(chan usecase.AgentRuntimeEvent)
	go func() {
		defer close(out)
		for event := range s.sub.Events() {
			out <- usecase.AgentRuntimeEvent{
				EventID:   event.EventID,
				EventType: string(event.EventType),
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
