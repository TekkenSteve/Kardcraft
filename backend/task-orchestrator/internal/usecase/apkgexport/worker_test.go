package apkgexport

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/riverqueue/river"
	"github.com/riverqueue/river/rivertype"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
)

func TestInferFieldNames(t *testing.T) {
	got := inferFieldNames("{{Front}} {{#Extra}}{{Hint:Back}}{{/Extra}}", "{{Back}}")
	want := []string{"Front", "Extra", "Back"}
	if len(got) != len(want) {
		t.Fatalf("field count = %d, want %d: %#v", len(got), len(want), got)
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("field %d = %q, want %q", index, got[index], want[index])
		}
	}
}

func TestExportCardFields(t *testing.T) {
	card := exportCard{}
	card.Content.Data = map[string]json.RawMessage{
		"front": json.RawMessage(`"Question"`), "back": json.RawMessage(`"Answer"`), "tags": json.RawMessage(`["one tag", "two"]`),
	}
	fields, tags := card.exportFields([]string{"Front", "Back", "Deck", "Tags"}, "Deck")
	if fields["Front"] != "Question" || fields["Back"] != "Answer" || fields["Deck"] != "Deck" || fields["Tags"] != "one_tag two" {
		t.Fatalf("unexpected fields: %#v", fields)
	}
	if len(tags) != 2 || tags[0] != "one_tag" || tags[1] != "two" {
		t.Fatalf("unexpected tags: %#v", tags)
	}
}

func TestWorkerKeepsExportQueuedUntilRiverExhaustsRetries(t *testing.T) {
	store := &workerExportStore{export: repo.APKGExport{ExportID: "export-1", Status: "queued"}}
	worker, err := NewWorker(failingWorkspace{}, store, unusedBuilder{})
	if err != nil {
		t.Fatalf("NewWorker: %v", err)
	}
	job := &river.Job[repo.APKGExportJobArgs]{JobRow: &rivertype.JobRow{Attempt: 1, MaxAttempts: 3}, Args: repo.APKGExportJobArgs{ExportID: "export-1"}}
	if err := worker.Work(context.Background(), job); err == nil {
		t.Fatal("Work error = nil, want build error")
	}
	if store.retries != 1 || store.failures != 0 {
		t.Fatalf("retry state retries=%d failures=%d, want 1 and 0", store.retries, store.failures)
	}

	job.Attempt = job.MaxAttempts
	if err := worker.Work(context.Background(), job); err == nil {
		t.Fatal("Work final error = nil, want build error")
	}
	if store.failures != 1 {
		t.Fatalf("final failures = %d, want one", store.failures)
	}
}

type workerExportStore struct {
	repo.APKGExportStore
	export   repo.APKGExport
	retries  int
	failures int
}

func (s *workerExportStore) GetAPKGExportByID(context.Context, string) (repo.APKGExport, bool, error) {
	return s.export, true, nil
}
func (s *workerExportStore) MarkAPKGExportRunning(context.Context, string) error { return nil }
func (s *workerExportStore) RetryAPKGExport(context.Context, string, string) error {
	s.retries++
	return nil
}
func (s *workerExportStore) FailAPKGExport(context.Context, string, string) error {
	s.failures++
	return nil
}

type failingWorkspace struct{ usecase.ReadModel }

func (failingWorkspace) LoadWorkspace(context.Context, string) (map[string]any, error) {
	return nil, errors.New("database unavailable")
}

type unusedBuilder struct{ usecase.APKGBuilder }
