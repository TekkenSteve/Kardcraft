package template

import (
	"context"
	"testing"

	"task-orchestrator/internal/usecase"
)

func TestPrepareTemplateOperationUsesAccessibleTemplateDefinition(t *testing.T) {
	store := &templateStore{template: &usecase.TemplateCatalogRow{
		TemplateID: "template-1", LatestVersion: 3, FrontHTML: "<div>{{Front}}</div>", BackHTML: "<div>{{Back}}</div>", CSS: ".card{}", JS: "console.log('x')", MappingSpec: map[string]any{"profile": "basic"},
	}}
	service, err := New(store, templateRuntime{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	prepared, err := service.PrepareTemplateOperation(context.Background(), "user-1", usecase.TemplateOperationCommand{Operation: usecase.TemplateOperationPreview, Payload: map[string]any{"template_id": "template-1"}})
	if err != nil {
		t.Fatalf("PrepareTemplateOperation: %v", err)
	}
	if prepared.Payload["front_html"] != "<div>{{Front}}</div>" || prepared.Payload["version"] != 3 {
		t.Fatalf("prepared payload = %#v", prepared.Payload)
	}
	if prepared.Payload["mapping_spec"].(map[string]any)["profile"] != "basic" {
		t.Fatalf("mapping spec = %#v", prepared.Payload["mapping_spec"])
	}
}

func TestTemplateCatalogOperationsUseApplicationPorts(t *testing.T) {
	store := &templateStore{
		rows:            []usecase.TemplateCatalogRow{{TemplateID: "template-1", Name: "Basic", LatestVersion: 2}},
		defaultTemplate: &usecase.TemplateCatalogRow{DefaultTemplateID: "template-1", DefaultTemplateVersion: 2},
		imported:        usecase.TemplateCatalogRow{TemplateID: "template-imported", LatestVersion: 1},
	}
	service, err := New(store, templateRuntime{})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	listed, err := service.ListTemplates(context.Background(), "user-1", 20, 0)
	if err != nil {
		t.Fatalf("ListTemplates: %v", err)
	}
	if len(listed.Templates) != 1 || !listed.Templates[0].IsDefault {
		t.Fatalf("template list = %#v", listed)
	}
	imported, err := service.ImportTemplate(context.Background(), "user-1", usecase.TemplateImportCommand{Name: "Imported", FrontHTML: "{{Front}}", BackHTML: "{{Back}}", CSS: ".card{}"})
	if err != nil {
		t.Fatalf("ImportTemplate: %v", err)
	}
	if imported.TemplateID != "template-imported" || store.importUserID != "user-1" {
		t.Fatalf("import result=%#v user=%q", imported, store.importUserID)
	}
	defaultTemplate, err := service.GetDefaultTemplate(context.Background(), "user-1")
	if err != nil {
		t.Fatalf("GetDefaultTemplate: %v", err)
	}
	if defaultTemplate.TemplateID != "template-1" || defaultTemplate.Version != 2 {
		t.Fatalf("default template = %#v", defaultTemplate)
	}
}

type templateStore struct {
	usecase.ReadModel
	template        *usecase.TemplateCatalogRow
	rows            []usecase.TemplateCatalogRow
	defaultTemplate *usecase.TemplateCatalogRow
	imported        usecase.TemplateCatalogRow
	importUserID    string
}

func (s *templateStore) GetAccessibleTemplate(context.Context, string, string) (*usecase.TemplateCatalogRow, error) {
	return s.template, nil
}
func (s *templateStore) ListAccessibleTemplates(context.Context, string, int, int) ([]usecase.TemplateCatalogRow, int, error) {
	return s.rows, len(s.rows), nil
}
func (s *templateStore) GetResolvedDefaultTemplate(context.Context, string) (*usecase.TemplateCatalogRow, error) {
	return s.defaultTemplate, nil
}
func (s *templateStore) ImportUserTemplate(_ context.Context, userID string, _ usecase.TemplateImport) (usecase.TemplateCatalogRow, error) {
	s.importUserID = userID
	return s.imported, nil
}

type templateRuntime struct{ usecase.TemplateRuntime }
