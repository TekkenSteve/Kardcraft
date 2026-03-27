package persistence

import (
	"context"
	"sort"
	"sync"

	"task-orchestrator/internal/entity/task"
)

type InMemoryTaskRepository struct {
	mu       sync.RWMutex
	store    map[string]task.TaskSnapshot
	inserted []string
}

func NewInMemoryTaskRepository() *InMemoryTaskRepository {
	return &InMemoryTaskRepository{store: make(map[string]task.TaskSnapshot)}
}

func (r *InMemoryTaskRepository) GetByID(_ context.Context, id task.TaskID) (*task.Task, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	snapshot, ok := r.store[id.String()]
	if !ok {
		return nil, nil
	}
	return task.RestoreTask(snapshot), nil
}

func (r *InMemoryTaskRepository) Save(_ context.Context, aggregate *task.Task) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := aggregate.ID().String()
	if _, exists := r.store[key]; !exists {
		r.inserted = append(r.inserted, key)
	}
	r.store[key] = aggregate.Snapshot()
	return nil
}

func (r *InMemoryTaskRepository) List(_ context.Context, filter task.ListFilter) ([]*task.Task, int, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	keys := make([]string, 0, len(r.inserted))
	for _, id := range r.inserted {
		snapshot, ok := r.store[id]
		if !ok {
			continue
		}
		if filter.UserID != "" && snapshot.UserID != filter.UserID {
			continue
		}
		keys = append(keys, id)
	}

	sort.SliceStable(keys, func(i, j int) bool {
		left := r.store[keys[i]]
		right := r.store[keys[j]]
		return left.CreatedAt.After(right.CreatedAt)
	})

	total := len(keys)
	start := filter.Offset
	if start > total {
		start = total
	}
	end := start + filter.Limit
	if filter.Limit <= 0 || end > total {
		end = total
	}
	selected := keys[start:end]
	out := make([]*task.Task, 0, len(selected))
	for _, key := range selected {
		out = append(out, task.RestoreTask(r.store[key]))
	}
	return out, total, nil
}

type EventHook func(events []task.DomainEvent)

type InMemoryEventPublisher struct {
	mu     sync.Mutex
	events []task.DomainEvent
	hooks  []EventHook
}

func NewInMemoryEventPublisher() *InMemoryEventPublisher {
	return &InMemoryEventPublisher{}
}

func (p *InMemoryEventPublisher) AddHook(hook EventHook) {
	if hook == nil {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	p.hooks = append(p.hooks, hook)
}

func (p *InMemoryEventPublisher) Publish(_ context.Context, events []task.DomainEvent) error {
	if len(events) == 0 {
		return nil
	}
	p.mu.Lock()
	p.events = append(p.events, events...)
	hooks := make([]EventHook, len(p.hooks))
	copy(hooks, p.hooks)
	p.mu.Unlock()

	for _, hook := range hooks {
		hook(events)
	}
	return nil
}

func (p *InMemoryEventPublisher) Events() []task.DomainEvent {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := make([]task.DomainEvent, len(p.events))
	copy(out, p.events)
	return out
}
