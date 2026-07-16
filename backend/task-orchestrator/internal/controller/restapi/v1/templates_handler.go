package v1

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

type TemplatesDeps struct {
	WriteJSON    func(w http.ResponseWriter, status int, v any)
	WriteRawJSON func(w http.ResponseWriter, status int, body []byte)
	UserID       func(r *http.Request) string
	NowRFC3339   func() string

	Service usecase.TemplateOperations
}

func NewCardTemplatesHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if deps.Service == nil {
			http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
			return
		}
		switch r.Method {
		case http.MethodGet:
			limit := 50
			offset := 0
			if raw := r.URL.Query().Get("limit"); raw != "" {
				if n, err := strconv.Atoi(raw); err == nil {
					limit = n
				}
			}
			if raw := r.URL.Query().Get("offset"); raw != "" {
				if n, err := strconv.Atoi(raw); err == nil {
					offset = n
				}
			}
			userID := deps.UserID(r)
			result, err := deps.Service.ListTemplates(r.Context(), userID, limit, offset)
			if err != nil {
				http.Error(w, "failed to list templates", http.StatusInternalServerError)
				return
			}
			list := make([]map[string]any, 0, len(result.Templates))
			for _, row := range result.Templates {
				list = append(list, map[string]any{
					"template_id":       row.TemplateID,
					"name":              row.Name,
					"description":       row.Description,
					"scope":             row.Scope,
					"owner_user_id":     row.OwnerUserID,
					"status":            row.Status,
					"is_default":        row.IsDefault,
					"latest_version":    row.LatestVersion,
					"version_published": row.VersionPublished,
					"created_at":        row.CreatedAt.UTC().Format(time.RFC3339),
					"updated_at":        row.UpdatedAt.UTC().Format(time.RFC3339),
				})
			}
			resp := map[string]any{"templates": list, "total_count": result.TotalCount}
			if result.UserDefaultTemplateID != "" {
				resp["user_default_template_id"] = result.UserDefaultTemplateID
				resp["user_default_template_version"] = result.UserDefaultTemplateVersion
			}
			deps.WriteJSON(w, http.StatusOK, resp)
		case http.MethodPost:
			handleTemplateImport(w, r, deps)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func handleTemplateImport(w http.ResponseWriter, r *http.Request, deps TemplatesDeps) {
	var payload map[string]any
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	templatePayload := MapFromAny(payload["template"])
	versionPayload := MapFromAny(payload["version"])
	if templatePayload == nil {
		templatePayload = payload
	}
	if versionPayload == nil {
		versionPayload = payload
	}
	name := strings.TrimSpace(StringOrDefault(templatePayload["name"], ""))
	frontHTML := StringOrDefault(versionPayload["front_html"], "")
	backHTML := StringOrDefault(versionPayload["back_html"], "")
	css := StringOrDefault(versionPayload["css"], "")
	if name == "" || strings.TrimSpace(frontHTML) == "" || strings.TrimSpace(backHTML) == "" || strings.TrimSpace(css) == "" {
		http.Error(w, "name, front_html, back_html, and css are required", http.StatusBadRequest)
		return
	}
	published := true
	if raw, ok := versionPayload["is_published"].(bool); ok {
		published = raw
	}
	if deps.Service == nil {
		http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
		return
	}
	result, err := deps.Service.ImportTemplate(r.Context(), deps.UserID(r), usecase.TemplateImportCommand{
		SourceTemplateID: StringOrDefault(templatePayload["template_id"], StringOrDefault(versionPayload["template_id"], "")),
		Name:             name,
		Description:      StringOrDefault(templatePayload["description"], ""),
		Tags:             templatePayload["tags"],
		Metadata:         MapFromAny(templatePayload["metadata"]),
		FrontHTML:        frontHTML,
		BackHTML:         backHTML,
		CSS:              css,
		JS:               StringOrDefault(versionPayload["js"], ""),
		MappingSpec:      MapFromAny(versionPayload["mapping_spec"]),
		AssetsManifest:   MapFromAny(versionPayload["assets_manifest"]),
		Compatibility:    MapFromAny(versionPayload["compatibility"]),
		Changelog:        StringOrDefault(versionPayload["changelog"], ""),
		Published:        published,
	})
	if err != nil {
		http.Error(w, "failed to import template", http.StatusInternalServerError)
		return
	}
	deps.WriteJSON(w, http.StatusCreated, map[string]any{
		"ok":             true,
		"template_id":    result.TemplateID,
		"version":        result.Version,
		"schema_version": "kctpl/v1",
	})
}

func NewCardTemplateDetailHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/card-templates/"), "/")
		if trimmed == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(trimmed, "/")
		templateID := parts[0]
		if len(parts) > 1 && parts[1] == "export" {
			handleTemplateExport(w, r, templateID, deps)
			return
		}
		if deps.Service == nil {
			http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "template mutation is not supported by task-orchestrator", http.StatusNotImplemented)
			return
		}
		row, err := deps.Service.GetTemplate(r.Context(), deps.UserID(r), templateID)
		if err != nil {
			http.Error(w, "template not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"template_id":       row.TemplateID,
			"name":              row.Name,
			"description":       row.Description,
			"scope":             row.Scope,
			"owner_user_id":     row.OwnerUserID,
			"status":            row.Status,
			"is_default":        row.IsDefault,
			"latest_version":    row.LatestVersion,
			"version_published": row.VersionPublished,
			"created_at":        row.CreatedAt.UTC().Format(time.RFC3339),
			"updated_at":        row.UpdatedAt.UTC().Format(time.RFC3339),
		})
	}
}

func NewCardTemplatePreviewHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		payload := map[string]any{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		proxyPayload := map[string]any{
			"template_id":      StringOrDefault(payload["template_id"], ""),
			"version":          IntOrDefault(payload["version"], 1),
			"front_html":       StringOrDefault(payload["front_html"], ""),
			"back_html":        StringOrDefault(payload["back_html"], ""),
			"css":              StringOrDefault(payload["css"], ""),
			"js":               StringOrDefault(payload["js"], ""),
			"sample_fields":    payload["sample_fields"],
			"template_profile": StringOrDefault(payload["template_profile"], ""),
			"card_type":        StringOrDefault(payload["card_type"], ""),
			"preview_mode":     StringOrDefault(payload["preview_mode"], "high_fidelity"),
			"render_target":    StringOrDefault(payload["render_target"], "anki"),
			"mapping_spec":     payload["mapping_spec"],
		}
		prepared, err := prepareTemplateOperation(r.Context(), deps, deps.UserID(r), usecase.TemplateOperationPreview, proxyPayload)
		if err != nil {
			http.Error(w, "invalid preview template", http.StatusBadRequest)
			return
		}
		proxyPayload = prepared.Payload
		templateMappingSpec := MapFromAny(proxyPayload["mapping_spec"])
		availableProfiles, defaultProfile := ExtractTemplateProfiles(templateMappingSpec)
		if strings.TrimSpace(StringOrDefault(payload["template_profile"], "")) == "" && defaultProfile != "" {
			proxyPayload["template_profile"] = defaultProfile
		}
		if sample, ok := ResolveSampleFieldsFromMapping(templateMappingSpec, strings.TrimSpace(StringOrDefault(proxyPayload["template_profile"], ""))); ok {
			if _, exists := proxyPayload["sample_fields"]; !exists || MapFromAny(proxyPayload["sample_fields"]) == nil {
				proxyPayload["sample_fields"] = sample
			}
		}
		result, err := executeTemplateOperation(r.Context(), deps, usecase.TemplateOperationPreview, proxyPayload)
		if err != nil {
			http.Error(w, "anki runtime preview unavailable", http.StatusBadGateway)
			return
		}
		if result.StatusCode < 200 || result.StatusCode >= 300 {
			w.WriteHeader(result.StatusCode)
			_, _ = w.Write(result.Body)
			return
		}
		var previewResp map[string]any
		if err := json.Unmarshal(result.Body, &previewResp); err != nil {
			deps.WriteRawJSON(w, result.StatusCode, result.Body)
			return
		}
		if _, ok := previewResp["available_profiles"]; !ok || len(StringSliceFromAny(previewResp["available_profiles"])) == 0 {
			if len(availableProfiles) > 0 {
				previewResp["available_profiles"] = availableProfiles
			}
		}
		if profile := strings.TrimSpace(StringOrDefault(previewResp["template_profile"], "")); profile == "" {
			if selected := strings.TrimSpace(StringOrDefault(proxyPayload["template_profile"], "")); selected != "" {
				previewResp["template_profile"] = selected
			} else if defaultProfile != "" {
				previewResp["template_profile"] = defaultProfile
			}
		}
		if mapping, ok := previewResp["mapping_spec"]; !ok || mapping == nil {
			if len(templateMappingSpec) > 0 {
				previewResp["mapping_spec"] = templateMappingSpec
			}
		}
		deps.WriteJSON(w, result.StatusCode, previewResp)
	}
}

func NewCardTemplateValidateHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback(usecase.TemplateOperationValidate, deps, true)
}

func NewCardTemplateRequiredFieldsHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback(usecase.TemplateOperationRequiredFields, deps, false)
}

func NewCardTemplatePrecheckHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback(usecase.TemplateOperationPrecheck, deps, false)
}

func NewCardTemplateBuildApkgHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		payload := map[string]any{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		result, err := executeTemplateOperation(r.Context(), deps, usecase.TemplateOperationBuildAPKG, payload)
		if err != nil {
			http.Error(w, "anki runtime build-apkg unavailable", http.StatusBadGateway)
			return
		}
		if result.StatusCode < 200 || result.StatusCode >= 300 {
			w.WriteHeader(result.StatusCode)
			_, _ = w.Write(result.Body)
			return
		}
		deps.WriteRawJSON(w, result.StatusCode, result.Body)
	}
}

func NewUserTemplatePreferencesHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Service == nil {
			http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := deps.UserID(r)
		switch r.Method {
		case http.MethodGet:
			pref, err := deps.Service.GetDefaultTemplate(r.Context(), userID)
			if err != nil {
				http.Error(w, "no default template configured", http.StatusNotFound)
				return
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{
				"user_id":                  userID,
				"default_template_id":      pref.TemplateID,
				"default_template_version": pref.Version,
				"updated_at":               deps.NowRFC3339(),
			})
		case http.MethodPost:
			var req struct {
				DefaultTemplateID      string `json:"default_template_id"`
				DefaultTemplateVersion int    `json:"default_template_version"`
			}
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				http.Error(w, "invalid request body", http.StatusBadRequest)
				return
			}
			if strings.TrimSpace(req.DefaultTemplateID) == "" {
				http.Error(w, "default_template_id is required", http.StatusBadRequest)
				return
			}
			if req.DefaultTemplateVersion <= 0 {
				req.DefaultTemplateVersion = 1
			}
			result, err := deps.Service.SetDefaultTemplate(r.Context(), userID, usecase.SetDefaultTemplateCommand{TemplateID: req.DefaultTemplateID, Version: req.DefaultTemplateVersion})
			if err != nil {
				http.Error(w, "failed to update user template preference", http.StatusInternalServerError)
				return
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{
				"user_id":                  userID,
				"default_template_id":      result.TemplateID,
				"default_template_version": result.Version,
				"updated_at":               deps.NowRFC3339(),
			})
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func handleTemplateExport(w http.ResponseWriter, r *http.Request, templateID string, deps TemplatesDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.Service == nil {
		http.Error(w, "template service unavailable", http.StatusServiceUnavailable)
		return
	}
	result, err := deps.Service.ExportTemplate(r.Context(), deps.UserID(r), templateID, time.Now().UTC())
	if err != nil {
		http.Error(w, "template not found", http.StatusNotFound)
		return
	}
	row := result.Template
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"schema_version": "kctpl/v1",
		"exported_at":    result.ExportedAt.Format(time.RFC3339),
		"template": map[string]any{
			"template_id":       row.TemplateID,
			"name":              row.Name,
			"description":       row.Description,
			"scope":             row.Scope,
			"owner_user_id":     row.OwnerUserID,
			"status":            row.Status,
			"is_default":        row.IsDefault,
			"latest_version":    row.LatestVersion,
			"version_published": row.VersionPublished,
			"created_at":        row.CreatedAt.UTC().Format(time.RFC3339),
			"updated_at":        row.UpdatedAt.UTC().Format(time.RFC3339),
			"tags":              row.Tags,
			"metadata":          row.Metadata,
		},
		"version": map[string]any{
			"template_id":     row.TemplateID,
			"version":         row.LatestVersion,
			"front_html":      row.FrontHTML,
			"back_html":       row.BackHTML,
			"css":             row.CSS,
			"js":              row.JS,
			"is_published":    row.VersionPublished,
			"mapping_spec":    row.MappingSpec,
			"assets_manifest": row.AssetsManifest,
			"compatibility":   row.Compatibility,
			"changelog":       row.Changelog,
		},
	})
}

func templateProxyWithTemplateFallback(operation usecase.TemplateOperation, deps TemplatesDeps, withJS bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		payload := map[string]any{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		prepared, err := prepareTemplateOperation(r.Context(), deps, deps.UserID(r), operation, payload)
		if err != nil {
			http.Error(w, "invalid template operation", http.StatusBadRequest)
			return
		}
		if !withJS {
			delete(prepared.Payload, "js")
		}
		result, err := executeTemplateOperation(r.Context(), deps, operation, prepared.Payload)
		if err != nil {
			http.Error(w, "anki runtime unavailable", http.StatusBadGateway)
			return
		}
		if result.StatusCode < 200 || result.StatusCode >= 300 {
			w.WriteHeader(result.StatusCode)
			_, _ = w.Write(result.Body)
			return
		}
		deps.WriteRawJSON(w, result.StatusCode, result.Body)
	}
}

func prepareTemplateOperation(ctx context.Context, deps TemplatesDeps, userID string, operation usecase.TemplateOperation, payload map[string]any) (usecase.TemplateOperationCommand, error) {
	if deps.Service == nil {
		return usecase.TemplateOperationCommand{}, fmt.Errorf("template service unavailable")
	}
	return deps.Service.PrepareTemplateOperation(ctx, userID, usecase.TemplateOperationCommand{Operation: operation, Payload: payload})
}

func executeTemplateOperation(ctx context.Context, deps TemplatesDeps, operation usecase.TemplateOperation, payload map[string]any) (usecase.TemplateOperationResult, error) {
	if deps.Service == nil {
		return usecase.TemplateOperationResult{}, fmt.Errorf("template service unavailable")
	}
	return deps.Service.ExecuteTemplateOperation(ctx, usecase.TemplateOperationCommand{Operation: operation, Payload: payload})
}
