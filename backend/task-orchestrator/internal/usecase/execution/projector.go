package execution

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/outcomeprojector"
)

// ProjectionStore is the Kardcraft read-model boundary updated from durable
// task execution events. It contains no AgentOS dependency.
type ProjectionStore interface {
	outcomeprojector.Store
	UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error
}

// Projector reconciles every nonterminal task against its durable execution
// stream. The execution runtime handles replay/order; PostgreSQL uniqueness on
// (workflow_id, stream_id) makes local event projection idempotent.
type Projector struct {
	execution usecase.TaskExecution
	routes    repo.TaskExecutionRouteStore
	store     ProjectionStore

	mu      sync.Mutex
	running map[string]context.CancelFunc
}

func NewProjector(execution usecase.TaskExecution, routes repo.TaskExecutionRouteStore, store ProjectionStore) (*Projector, error) {
	if execution == nil || routes == nil || store == nil {
		return nil, fmt.Errorf("execution, route store, and projection store are required")
	}

	return &Projector{execution: execution, routes: routes, store: store, running: make(map[string]context.CancelFunc)}, nil
}

// Reconcile starts durable consumers for all unfinished task executions. It is
// safe to call repeatedly, which allows startup recovery without duplicate
// subscribers.
func (p *Projector) Reconcile(ctx context.Context) error {
	routes, err := p.routes.ListActiveTaskExecutionRoutes(ctx)
	if err != nil {
		return err
	}
	for _, route := range routes {
		p.Start(route.TaskID)
	}

	return nil
}

// Run continuously discovers newly-created executions and restores consumers
// after process restart. Individual consumers always replay from the durable
// AgentOS stream, so discovery never loses events between passes.
func (p *Projector) Run(ctx context.Context, interval time.Duration) {
	if interval <= 0 {
		interval = 5 * time.Second
	}
	if err := p.Reconcile(ctx); err != nil {
		log.Printf("execution projector reconcile err=%v", err)
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			p.Close()
			return
		case <-ticker.C:
			if err := p.Reconcile(ctx); err != nil {
				log.Printf("execution projector reconcile err=%v", err)
			}
		}
	}
}

func (p *Projector) Start(taskID string) {
	if p == nil || strings.TrimSpace(taskID) == "" {
		return
	}
	p.mu.Lock()
	if _, exists := p.running[taskID]; exists {
		p.mu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	p.running[taskID] = cancel
	p.mu.Unlock()
	go p.consume(ctx, taskID)
}

func (p *Projector) Close() {
	if p == nil {
		return
	}
	p.mu.Lock()
	cancels := make([]context.CancelFunc, 0, len(p.running))
	for _, cancel := range p.running {
		cancels = append(cancels, cancel)
	}
	p.running = make(map[string]context.CancelFunc)
	p.mu.Unlock()
	for _, cancel := range cancels {
		cancel()
	}
}

func (p *Projector) consume(ctx context.Context, taskID string) {
	defer func() {
		p.mu.Lock()
		delete(p.running, taskID)
		p.mu.Unlock()
	}()
	subscription, err := p.execution.SubscribeTaskExecution(ctx, usecase.TaskExecutionEventScope{TaskID: taskID})
	if err != nil {
		log.Printf("execution projector subscribe task_id=%s err=%v", taskID, err)
		return
	}
	defer subscription.Close()
	for {
		select {
		case <-ctx.Done():
			return
		case event, open := <-subscription.Events():
			if !open {
				return
			}
			if err := p.Project(ctx, taskID, event); err != nil {
				log.Printf("execution projector event task_id=%s event_id=%s err=%v", taskID, event.EventID, err)
				return
			}
		}
	}
}

func (p *Projector) Project(ctx context.Context, taskID string, event usecase.TaskExecutionEvent) error {
	if p == nil || p.store == nil {
		return fmt.Errorf("execution projector is not configured")
	}
	taskID = strings.TrimSpace(taskID)
	if taskID == "" || strings.TrimSpace(event.EventID) == "" || event.Sequence <= 0 {
		return fmt.Errorf("task execution event requires task id, event id, and positive sequence")
	}
	sessionID, err := p.store.GetTaskSession(ctx, taskID)
	if err != nil {
		return fmt.Errorf("resolve task session: %w", err)
	}
	eventType := KardcraftEventType(event.EventType)
	payload := executionEventEnvelope(taskID, sessionID, eventType, event)
	if isTerminalEvent(eventType) {
		if outcome, ok := taskOutcome(event.Payload); ok {
			_, err := outcomeprojector.New(p.store).ProjectWithEvents(ctx, outcomeprojector.Input{
				TaskID:        taskID,
				WorkflowID:    taskID,
				RunID:         event.RunID,
				Status:        terminalStatus(eventType, outcome),
				Result:        outcome,
				Error:         stringValue(event.Payload["error"]),
				CompletedAt:   event.Timestamp,
				CorrelationID: stringValue(event.Payload["correlation_id"]),
				TerminalNote:  stringValue(event.Payload["message"]),
			})
			return err
		}
	}
	if status, ok := taskStatus(eventType); ok {
		if err := p.store.UpdateTaskStatus(ctx, taskID, status, stringValue(event.Payload["error"])); err != nil {
			return err
		}
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode execution event: %w", err)
	}
	return p.store.InsertEvent(ctx, sessionID, taskID, taskID, eventType, stringValue(event.Payload["message"]), string(encoded), "agentos:"+event.EventID, event.Timestamp)
}

func executionEventEnvelope(taskID, sessionID, eventType string, event usecase.TaskExecutionEvent) map[string]any {
	payload := make(map[string]any, len(event.Payload)+9)
	for key, value := range event.Payload {
		payload[key] = value
	}
	payload["schema_version"] = "kardcraft.execution-event.v1"
	payload["event_id"] = event.EventID
	payload["event_type"] = eventType
	payload["task_id"] = taskID
	payload["workflow_id"] = taskID
	payload["session_id"] = sessionID
	payload["run_id"] = event.RunID
	payload["sequence"] = event.Sequence
	payload["occurred_at"] = event.Timestamp.UTC().Format(time.RFC3339Nano)
	return payload
}

func taskOutcome(payload map[string]any) (map[string]any, bool) {
	if outcome, ok := payload["task_outcome"].(map[string]any); ok && len(outcome) > 0 {
		return outcome, true
	}
	if strings.EqualFold(stringValue(payload["schema_version"]), "task-outcome") {
		return payload, true
	}
	return nil, false
}

func terminalStatus(eventType string, outcome map[string]any) string {
	switch strings.ToLower(stringValue(outcome["status"])) {
	case "completed", "success", "succeeded":
		return "completed"
	case "failed", "error":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	}
	if eventType == usecase.EventWorkflowFailed {
		return "failed"
	}
	if eventType == usecase.EventWorkflowCancelled {
		return "cancelled"
	}
	return "completed"
}

func taskStatus(eventType string) (string, bool) {
	switch eventType {
	case usecase.EventWorkflowStarted, usecase.EventWorkflowWaitingInput, usecase.EventMessageReceived, usecase.EventWorkflowResumed, usecase.EventWorkflowProgress:
		return "running", true
	case usecase.EventWorkflowPaused:
		return "paused", true
	case usecase.EventWorkflowCompleted:
		return "completed", true
	case usecase.EventWorkflowFailed:
		return "failed", true
	case usecase.EventWorkflowCancelled:
		return "cancelled", true
	default:
		return "", false
	}
}

func isTerminalEvent(eventType string) bool {
	return eventType == usecase.EventWorkflowCompleted || eventType == usecase.EventWorkflowFailed || eventType == usecase.EventWorkflowCancelled
}

func stringValue(value any) string {
	text, _ := value.(string)
	return strings.TrimSpace(text)
}
