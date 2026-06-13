package handlers

import "testing"

func TestTimelineEventPayloadUsesCanonicalEnvelope(t *testing.T) {
	payload, runID := timelineEventPayload(map[string]any{
		"schema_version": 1,
		"run_id":         "run-1",
		"payload": map[string]any{
			"run_id":     "run-1",
			"node_name":  "card_scope_planner",
			"event_name": "card_scope_planner",
			"message":    "card_scope_planner completed",
		},
	})

	if runID != "run-1" {
		t.Fatalf("expected run_id run-1, got %q", runID)
	}
	record, ok := payload.(map[string]any)
	if !ok {
		t.Fatalf("expected timeline payload map, got %T", payload)
	}
	if record["node_name"] != "card_scope_planner" {
		t.Fatalf("expected node_name to remain in event payload, got %#v", record["node_name"])
	}
	if _, exists := record["schema_version"]; exists {
		t.Fatalf("expected envelope metadata to stay outside event payload")
	}
}
