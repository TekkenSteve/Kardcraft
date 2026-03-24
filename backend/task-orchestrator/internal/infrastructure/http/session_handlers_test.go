package httpserver

import (
	"reflect"
	"testing"

	"task-orchestrator/internal/infrastructure/persistence"
	"task-orchestrator/internal/infrastructure/temporal/workflows"
)

func TestNormalizeWorkspaceResponse_StableAcrossRepeatedCalls(t *testing.T) {
	raw := map[string]any{
		"session_id": "s1",
		"version":    2,
		"status":     "active",
		"cards": []any{
			map[string]any{
				"id":      "c1",
				"user_id": "u1",
				"card_id": "c1",
				"content": map[string]any{
					"version": 1,
					"model":   "mcq",
					"data": map[string]any{
						"front": "f",
						"back":  "b",
					},
				},
				"edit_state": map[string]any{"status": "draft"},
				"meta": map[string]any{
					"created_at":   "2026-03-18T00:00:00Z",
					"modified_at":  "2026-03-18T00:00:00Z",
					"manual_edits": 0,
				},
			},
		},
	}
	first := normalizeWorkspaceResponse(raw, "s1")
	second := normalizeWorkspaceResponse(raw, "s1")
	if !reflect.DeepEqual(first, second) {
		t.Fatalf("expected stable normalization result,\nfirst=%v\nsecond=%v", first, second)
	}
	if first["projection_status"] != "hydrated" {
		t.Fatalf("expected projection_status=hydrated, got %v", first["projection_status"])
	}
}

func TestExtractResultMessage_StrictContractByDefault(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	message := extractResultMessage(map[string]any{
		"message": "legacy-only-message",
	})
	if message != "" {
		t.Fatalf("expected empty message when fallback disabled, got %q", message)
	}
}

func TestExtractResultMessage_FallbackWhenEnabled(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "true")
	message := extractResultMessage(map[string]any{
		"message": "legacy-only-message",
	})
	if message != "legacy-only-message" {
		t.Fatalf("expected fallback message, got %q", message)
	}
}

func TestExtractResultMessage_FromCanonicalOutcome(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	outcome := workflows.TaskOutcome{
		SchemaVersion: workflows.TaskOutcomeSchema,
		TaskID:        "t1",
		WorkflowID:    "w1",
		Status:        "completed",
		Message:       "canonical-message",
	}
	message := extractResultMessage(outcome.ToMap())
	if message != "canonical-message" {
		t.Fatalf("expected canonical message, got %q", message)
	}
}

func TestExtractResultMessage_FromJSONStringEnvelope(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	raw := `{"result":{"data":{"message":"enveloped-message","status":"success"}}}`
	message := extractResultMessage(raw)
	if message != "enveloped-message" {
		t.Fatalf("expected enveloped-message, got %q", message)
	}
}

func TestResolveSessionActiveTask_PicksMostRecentActive(t *testing.T) {
	tasks := []persistence.TaskRow{
		{TaskID: "t1", Status: ptr("completed")},
		{TaskID: "t2", Status: ptr("running")},
		{TaskID: "t3", Status: ptr("paused")},
	}
	active, ok := resolveSessionActiveTask(tasks)
	if !ok {
		t.Fatalf("expected active task")
	}
	if active.TaskID != "t3" {
		t.Fatalf("expected t3, got %s", active.TaskID)
	}
}

func TestResolveSessionActiveTask_NoActive(t *testing.T) {
	tasks := []persistence.TaskRow{
		{TaskID: "t1", Status: ptr("completed")},
		{TaskID: "t2", Status: ptr("failed")},
		{TaskID: "t3", Status: ptr("cancelled")},
	}
	_, ok := resolveSessionActiveTask(tasks)
	if ok {
		t.Fatalf("expected no active task")
	}
}

func TestControlStateFromTaskState(t *testing.T) {
	if got := controlStateFromTaskState("RUNNING"); got != "ACTIVE_RUNNING" {
		t.Fatalf("expected ACTIVE_RUNNING, got %s", got)
	}
	if got := controlStateFromTaskState("PAUSED"); got != "ACTIVE_PAUSED" {
		t.Fatalf("expected ACTIVE_PAUSED, got %s", got)
	}
	if got := controlStateFromTaskState("CANCELED"); got != "IDLE" {
		t.Fatalf("expected IDLE, got %s", got)
	}
}

func TestIsTaskActiveStatusSet(t *testing.T) {
	active := []string{"pending", "queued", "running", "paused"}
	for _, status := range active {
		if !isTaskActiveStatus(status) {
			t.Fatalf("expected active status for %s", status)
		}
	}
	inactive := []string{"completed", "failed", "cancelled", "idle", ""}
	for _, status := range inactive {
		if isTaskActiveStatus(status) {
			t.Fatalf("expected inactive status for %s", status)
		}
	}
}

func ptr(v string) *string { return &v }
