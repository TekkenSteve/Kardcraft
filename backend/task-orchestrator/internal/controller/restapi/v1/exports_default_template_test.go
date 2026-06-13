package v1

import "testing"

func TestResolveExportTemplateID_UsesExplicitTemplate(t *testing.T) {
	got, err := resolveExportTemplateID("tpl-explicit", map[string]any{"template_id": "tpl-workspace"}, func() (string, error) {
		return "tpl-default", nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "tpl-explicit" {
		t.Fatalf("expected explicit template id, got %q", got)
	}
}

func TestResolveExportTemplateID_UsesWorkspaceTemplate(t *testing.T) {
	called := false
	got, err := resolveExportTemplateID("", map[string]any{"template_id": "tpl-workspace"}, func() (string, error) {
		called = true
		return "tpl-default", nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if called {
		t.Fatalf("resolver should not be called when workspace template exists")
	}
	if got != "tpl-workspace" {
		t.Fatalf("expected workspace template id, got %q", got)
	}
}

func TestResolveExportTemplateID_UsesResolvedDefault(t *testing.T) {
	got, err := resolveExportTemplateID("", map[string]any{}, func() (string, error) {
		return "tpl-default", nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "tpl-default" {
		t.Fatalf("expected resolved default template id, got %q", got)
	}
}

func TestResolveExportTemplateID_FailsWithoutDefault(t *testing.T) {
	_, err := resolveExportTemplateID("", map[string]any{}, func() (string, error) {
		return "", nil
	})
	if err == nil {
		t.Fatalf("expected error when no template can be resolved")
	}
}
