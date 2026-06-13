package entity

import "context"

type ListFilter struct {
	UserID string
	Limit  int
	Offset int
}

type Repository interface {
	GetByID(ctx context.Context, id TaskID) (*Task, error)
	Save(ctx context.Context, aggregate *Task) error
	List(ctx context.Context, filter ListFilter) ([]*Task, int, error)
}

type EventPublisher interface {
	Publish(ctx context.Context, events []DomainEvent) error
}
