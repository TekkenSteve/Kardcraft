package temporal

import "testing"

func TestDecodeTaskOutcomeCanonical(t *testing.T) {
	input := map[string]any{
		"schema_version": TaskOutcomeSchema,
		"task_id":        "t1",
		"workflow_id":    "w1",
		"status":         "completed",
		"session_id":     "s1",
		"user_id":        "u1",
		"message":        "ok",
		"final_cards": []any{
			map[string]any{
				"id":    "c1",
				"front": "f",
				"back":  "b",
				"model": "mcq",
				"tags":  []any{"x"},
			},
		},
	}
	out, err := DecodeTaskOutcome(input)
	if err != nil {
		t.Fatalf("expected decode success, got err=%v", err)
	}
	if out.Status != "completed" || out.TaskID != "t1" || len(out.FinalCards) != 1 {
		t.Fatalf("unexpected decoded outcome: %+v", out)
	}
}

func TestDecodeTaskOutcomeRejectsUnknownSchema(t *testing.T) {
	input := map[string]any{
		"schema_version": "task-outcome.v9",
		"status":         "completed",
	}
	_, err := DecodeTaskOutcome(input)
	if err == nil {
		t.Fatalf("expected decode failure with unknown schema version")
	}
}

func TestDecodeTaskOutcomeRejectsMissingStatus(t *testing.T) {
	input := map[string]any{
		"schema_version": TaskOutcomeSchema,
		"message":        "done",
	}
	_, err := DecodeTaskOutcome(input)
	if err == nil {
		t.Fatalf("expected decode failure with missing status")
	}
}
