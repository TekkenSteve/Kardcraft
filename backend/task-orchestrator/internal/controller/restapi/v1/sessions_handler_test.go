package v1

import (
	"reflect"
	"task-orchestrator/internal/controller/temporal"
	"task-orchestrator/internal/usecase"
	"testing"
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
	first := NormalizeWorkspaceResponse(raw, "s1")
	second := NormalizeWorkspaceResponse(raw, "s1")
	if !reflect.DeepEqual(first, second) {
		t.Fatalf("expected stable normalization result,\nfirst=%v\nsecond=%v", first, second)
	}
	if first["projection_status"] != "hydrated" {
		t.Fatalf("expected projection_status=hydrated, got %v", first["projection_status"])
	}
}

func TestNormalizeWorkspaceResponse_AcceptsPackWorkspaceCardShape(t *testing.T) {
	raw := map[string]any{
		"session_id": "s1",
		"version":    2,
		"status":     "active",
		"cards": []any{
			map[string]any{
				"temp_id": "card_tmp_1",
				"model":   "mcq",
				"status":  "output_draft",
				"content": map[string]any{
					"front": "front text",
					"back":  "back text",
					"tags":  []any{"tag-a"},
				},
				"modified_at": "2026-04-16T05:24:21Z",
			},
		},
	}

	normalized := NormalizeWorkspaceResponse(raw, "s1")
	if normalized["projection_status"] != "hydrated" {
		t.Fatalf("expected projection_status=hydrated, got %v", normalized["projection_status"])
	}
	if normalized["card_count"] != 1 {
		t.Fatalf("expected card_count=1, got %v", normalized["card_count"])
	}

	cards, ok := normalized["cards"].([]map[string]any)
	if !ok || len(cards) != 1 {
		t.Fatalf("expected exactly one normalized card, got %#v", normalized["cards"])
	}

	card := cards[0]
	if cardID, _ := card["card_id"].(string); cardID != "card_tmp_1" {
		t.Fatalf("expected card_id=card_tmp_1, got %q", cardID)
	}
	editState, _ := card["edit_state"].(map[string]any)
	if status, _ := editState["status"].(string); status != "draft" {
		t.Fatalf("expected mapped status=draft, got %q", status)
	}
	content, _ := card["content"].(map[string]any)
	data, _ := content["data"].(map[string]any)
	if front, _ := data["front"].(string); front != "front text" {
		t.Fatalf("expected front text, got %q", front)
	}
	if back, _ := data["back"].(string); back != "back text" {
		t.Fatalf("expected back text, got %q", back)
	}
}

func TestExtractResultMessage_StrictContractByDefault(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	message := ExtractResultMessage(map[string]any{
		"message": "legacy-only-message",
	})
	if message != "" {
		t.Fatalf("expected empty message when fallback disabled, got %q", message)
	}
}

func TestExtractResultMessage_FallbackWhenEnabled(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "true")
	message := ExtractResultMessage(map[string]any{
		"message": "legacy-only-message",
	})
	if message != "legacy-only-message" {
		t.Fatalf("expected fallback message, got %q", message)
	}
}

func TestExtractResultMessage_FromCanonicalOutcome(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	outcome := temporal.TaskOutcome{
		SchemaVersion: temporal.TaskOutcomeSchema,
		TaskID:        "t1",
		WorkflowID:    "w1",
		Status:        "completed",
		Message:       "canonical-message",
	}
	message := ExtractResultMessage(outcome.ToMap())
	if message != "canonical-message" {
		t.Fatalf("expected canonical message, got %q", message)
	}
}

func TestExtractResultMessage_FromJSONStringEnvelope(t *testing.T) {
	t.Setenv("TASK_READ_PATH_BACKFILL_ENABLED", "false")
	raw := `{"result":{"data":{"message":"enveloped-message","status":"success"}}}`
	message := ExtractResultMessage(raw)
	if message != "enveloped-message" {
		t.Fatalf("expected enveloped-message, got %q", message)
	}
}

func TestResolveSessionActiveTask_PicksMostRecentActive(t *testing.T) {
	tasks := []usecase.TaskRow{
		{TaskID: "t1", Status: ptr("completed")},
		{TaskID: "t2", Status: ptr("running")},
		{TaskID: "t3", Status: ptr("paused")},
	}
	active, ok := ResolveSessionActiveTask(tasks)
	if !ok {
		t.Fatalf("expected active task")
	}
	if active.TaskID != "t3" {
		t.Fatalf("expected t3, got %s", active.TaskID)
	}
}

func TestResolveSessionActiveTask_NoActive(t *testing.T) {
	tasks := []usecase.TaskRow{
		{TaskID: "t1", Status: ptr("completed")},
		{TaskID: "t2", Status: ptr("failed")},
		{TaskID: "t3", Status: ptr("cancelled")},
	}
	_, ok := ResolveSessionActiveTask(tasks)
	if ok {
		t.Fatalf("expected no active task")
	}
}

func TestControlStateFromTaskState(t *testing.T) {
	if got := ControlStateFromTaskState("RUNNING"); got != "ACTIVE_RUNNING" {
		t.Fatalf("expected ACTIVE_RUNNING, got %s", got)
	}
	if got := ControlStateFromTaskState("PAUSED"); got != "ACTIVE_PAUSED" {
		t.Fatalf("expected ACTIVE_PAUSED, got %s", got)
	}
	if got := ControlStateFromTaskState("CANCELED"); got != "IDLE" {
		t.Fatalf("expected IDLE, got %s", got)
	}
}

func TestIsTaskActiveStatusSet(t *testing.T) {
	active := []string{"pending", "queued", "running", "paused"}
	for _, status := range active {
		if !IsTaskActiveStatus(status) {
			t.Fatalf("expected active status for %s", status)
		}
	}
	inactive := []string{"completed", "failed", "cancelled", "idle", ""}
	for _, status := range inactive {
		if IsTaskActiveStatus(status) {
			t.Fatalf("expected inactive status for %s", status)
		}
	}
}

func ptr(v string) *string { return &v }
