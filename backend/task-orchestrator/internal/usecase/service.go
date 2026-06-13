package usecase

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/entity"
)

var ErrTaskNotFound = errors.New("task not found")

type Clock func() time.Time

type TaskService struct {
	repo      entity.Repository
	publisher entity.EventPublisher
	clock     Clock
}

type CreateTaskInput struct {
	TaskID    string
	TaskType  string
	UserID    string
	Query     string
	SessionID string
}

type ListTasksInput struct {
	UserID string
	Limit  int
	Offset int
}

func NewTaskService(repo entity.Repository, publisher entity.EventPublisher, clock Clock) *TaskService {
	if clock == nil {
		clock = time.Now
	}
	return &TaskService{repo: repo, publisher: publisher, clock: clock}
}

func (s *TaskService) CreateTask(ctx context.Context, in CreateTaskInput) (*entity.Task, error) {
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

func (s *TaskService) StartTask(ctx context.Context, rawTaskID string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Start(now)
	})
}

func (s *TaskService) CompleteTask(ctx context.Context, rawTaskID string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Complete(now)
	})
}

func (s *TaskService) FailTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Fail(now, reason)
	})
}

func (s *TaskService) PauseTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Pause(now, reason)
	})
}

func (s *TaskService) ResumeTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Resume(now, reason)
	})
}

func (s *TaskService) CancelTask(ctx context.Context, rawTaskID string, reason string) error {
	return s.transition(ctx, rawTaskID, func(t *entity.Task, now time.Time) error {
		return t.Cancel(now, reason)
	})
}

func (s *TaskService) GetTask(ctx context.Context, rawTaskID string) (*entity.Task, error) {
	taskID, err := entity.NewTaskID(rawTaskID)
	if err != nil {
		return nil, err
	}
	agg, err := s.repo.GetByID(ctx, taskID)
	if err != nil {
		return nil, err
	}
	if agg == nil {
		return nil, ErrTaskNotFound
	}
	return agg, nil
}

func (s *TaskService) ListTasks(ctx context.Context, in ListTasksInput) ([]*entity.Task, int, error) {
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

func (s *TaskService) transition(ctx context.Context, rawTaskID string, fn func(t *entity.Task, now time.Time) error) error {
	taskID, err := entity.NewTaskID(rawTaskID)
	if err != nil {
		return err
	}
	agg, err := s.repo.GetByID(ctx, taskID)
	if err != nil {
		return err
	}
	if agg == nil {
		return ErrTaskNotFound
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
