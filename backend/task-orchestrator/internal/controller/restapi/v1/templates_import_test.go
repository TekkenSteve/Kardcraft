package v1

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"task-orchestrator/internal/usecase"
)

func TestTemplateImportCreatesUserOwnedCopyAndPreservesPackageContent(t *testing.T) {
	store := &fakeReadModelStore{ready: true, importResult: usecase.TemplateCatalogRow{TemplateID: "tpl-copy", LatestVersion: 1}}
	handler := NewCardTemplatesHandler(TemplatesDeps{
		WriteJSON: writeJSON,
		UserID:    func(*http.Request) string { return "user-1" },
		ReadModel: store,
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/card-templates", strings.NewReader(`{
		"schema_version":"kctpl/v1",
		"template":{"template_id":"tpl-system","name":"Imported","tags":["language","review"],"metadata":{"origin":"community"}},
		"version":{"template_id":"tpl-system","version":4,"front_html":"{{Front}}","back_html":"{{Back}}","css":".card{}","js":"console.log(1)","mapping_spec":{"profiles":[]},"assets_manifest":{"images":[]},"compatibility":{"anki":"24"},"changelog":"imported","is_published":true}
	}`))
	recorder := httptest.NewRecorder()

	handler.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d body=%s", recorder.Code, recorder.Body.String())
	}
	if store.importedUserID != "user-1" || store.importedTemplate.SourceTemplateID != "tpl-system" || store.importedTemplate.Name != "Imported" {
		t.Fatalf("unexpected import ownership/input: user=%q input=%#v", store.importedUserID, store.importedTemplate)
	}
	tags, ok := store.importedTemplate.Tags.([]any)
	if !ok || len(tags) != 2 || tags[0] != "language" {
		t.Fatalf("expected tags array to be preserved, got %#v", store.importedTemplate.Tags)
	}
	if store.importedTemplate.AssetsManifest["images"] == nil || store.importedTemplate.Compatibility["anki"] != "24" || store.importedTemplate.Changelog != "imported" {
		t.Fatalf("expected package version content to be preserved, got %#v", store.importedTemplate)
	}
}
