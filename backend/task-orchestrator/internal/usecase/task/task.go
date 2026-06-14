package task

import (
	"context"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/entity"
	"task-orchestrator/internal/usecase"
)

type UseCase struct {
	repo      entity.Repository
	publisher entity.EventPublisher
	clock     usecase.Clock
}

func New(repo entity.Repository, publisher entity.EventPublisher, clock usecase.Clock) *UseCase {
	if clock == nil {
		clock = time.Now
	}
	return &UseCase{repo: repo, publisher: publisher, clock: clock}
}

func (s *UseCase) CreateTask(ctx context.Context, in usecase.CreateTaskInput) (*entity.Task, error) {
	taskID, err := entity.NewTaskID(in.TaskID)
	if err != nil {
		return nil, err
	}
	if existing, err := s.repo.GetByID(ctx, taskID); err != nil {
		return nil, err
	} else if existing != nil {
		return nil, fmt.Errorf("task already exists: %s", in.TaskID)
	}
	agg := entity.NewTask(taskID, in.TaskType, in.UserID, in.Query, in.SessionID, nil, s.clock())
	if err := s.repo.Save(ctx, agg); err != nil {
		return nil, err
	}
	events := agg.PullEvents()
	if len(events) > 0 {
		if err := s.publisher.Publish(ctx, events); err != nil {
			return nil, err
		}
	}
	return agg, nil
}

func (s *UseCase) StartTask(ctx context.Context, rawTaskID string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Start(now)
	})
}

func (s *UseCase) CompleteTask(ctx context.Context, rawTaskID string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Complete(now)
	})
}

func (s *UseCase) FailTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Fail(now, reason)
	})
}

func (s *UseCase) PauseTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Pause(now, reason)
	})
}

func (s *UseCase) ResumeTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Resume(now, reason)
	})
}

func (s *UseCase) CancelTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Cancel(now, reason)
	})
}

func (s *UseCase) GetTask(ctx context.Context, rawTaskID string) (*entity.Task, error) {
	taskID, err := entity.NewTaskID(rawTaskID)
	if err != nil {
		return nil, err
	}
	agg, err := s.repo.GetByID(ctx, taskID)
	if err != nil {
		return nil, err
	}
	if agg == nil {
		return nil, usecase.ErrTaskNotFound
	}
	return agg, nil
}

func (s *UseCase) ListTasks(ctx context.Context, in usecase.ListTasksInput) ([]*entity.Task, int, error) {
	limit := in.Limit
	offset := in.Offset
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	return s.repo.List(ctx, entity.ListFilter{UserID: strings.TrimSpace(in.UserID), Limit: limit, Offset: offset})
}

func (s *UseCase) transition(ctx context.Context, rawTaskID string, fn func(t *entity.Task, now time.Time) error) error {
	taskID, err := entity.NewTaskID(rawTaskID)
	if err != nil {
		return err
	}
	agg, err := s.repo.GetByID(ctx, taskID)
	if err != nil {
		return err
	}
	if agg == nil {
		return usecase.ErrTaskNotFound
	}
	if err := fn(agg, s.clock()); err != nil {
		return err
	}
	if err := s.repo.Save(ctx, agg); err != nil {
		return err
	}
	events := agg.PullEvents()
	if len(events) == 0 {
		return nil
	}
	return s.publisher.Publish(ctx, events)
}
