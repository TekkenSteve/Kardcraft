package temporal

import (
	"context"
	"fmt"

	"task-orchestrator/internal/usecase/outcomeprojector"
)

type PersistTaskOutcomeInput = outcomeprojector.Input

var taskOutcomeProjector *outcomeprojector.Projector

func ConfigureTaskPersistenceStore(store outcomeprojector.Store) {
	taskOutcomeProjector = outcomeprojector.New(store)
}

func PersistTaskOutcomeActivity(ctx context.Context, in PersistTaskOutcomeInput) error {
	if taskOutcomeProjector == nil {
		return fmt.Errorf("task outcome projector not configured")
	}
	return taskOutcomeProjector.Project(ctx, in)
}
