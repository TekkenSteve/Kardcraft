package temporal

import (
	"testing"

	"go.temporal.io/sdk/temporal"
)

func TestDecideResumeAfterPauseStartsResumeBeforePausedActivityCancellationCompletes(t *testing.T) {
	consumeResume, startResume := decideResumeAfterPause(true, false, nil)
	if !consumeResume {
		t.Fatalf("expected resume signal to be consumed")
	}
	if !startResume {
		t.Fatalf("expected resume activity to start without waiting for paused activity cancellation")
	}
}

func TestDecideResumeAfterPauseStartsResumeForCanceledActivity(t *testing.T) {
	consumeResume, startResume := decideResumeAfterPause(true, true, temporal.NewCanceledError("paused"))
	if !consumeResume {
		t.Fatalf("expected resume signal to be consumed")
	}
	if !startResume {
		t.Fatalf("expected resume activity to start after paused activity cancellation")
	}
}

func TestDecideResumeAfterPauseKeepsCompletedActivityResult(t *testing.T) {
	consumeResume, startResume := decideResumeAfterPause(true, true, nil)
	if !consumeResume {
		t.Fatalf("expected resume signal to be consumed")
	}
	if startResume {
		t.Fatalf("expected completed paused activity result to be kept")
	}
}
