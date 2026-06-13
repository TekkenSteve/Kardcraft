package restapi

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"task-orchestrator/internal/usecase"
)

type TemplatesDeps struct {
	WriteJSON    func(w http.ResponseWriter, status int, v any)
	WriteRawJSON func(w http.ResponseWriter, status int, body []byte)
	UserID       func(r *http.Request) string
	NowRFC3339   func() string

	HTTPClient     *http.Client
	AnkiRuntimeURL string
	ReadModel      *usecase.ReadModelService
}

func NewCardTemplatesHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if deps.ReadModel == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
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
			rows, total, err := deps.ReadModel.ListAccessibleTemplates(r.Context(), userID, limit, offset)
			if err != nil {
				http.Error(w, "failed to list templates", http.StatusInternalServerError)
				return
			}
			resolvedDefaultID := ""
			resolvedDefaultVersion := 0
			if resolved, err := deps.ReadModel.GetResolvedDefaultTemplate(r.Context(), userID); err == nil && resolved != nil {
				resolvedDefaultID = strings.TrimSpace(resolved.DefaultTemplateID)
				resolvedDefaultVersion = resolved.DefaultTemplateVersion
			}
			list := make([]map[string]any, 0, len(rows))
			for _, row := range rows {
				isResolvedDefault := resolvedDefaultID != "" && row.TemplateID == resolvedDefaultID
				list = append(list, map[string]any{
					"template_id":       row.TemplateID,
					"name":              row.Name,
					"description":       row.Description,
					"scope":             row.Scope,
					"owner_user_id":     row.OwnerUserID,
					"status":            row.Status,
					"is_default":        isResolvedDefault,
					"latest_version":    row.LatestVersion,
					"version_published": row.VersionPublished,
					"created_at":        row.CreatedAt.UTC().Format(time.RFC3339),
					"updated_at":        row.UpdatedAt.UTC().Format(time.RFC3339),
				})
			}
			resp := map[string]any{"templates": list, "total_count": total}
			if resolvedDefaultID != "" {
				resp["user_default_template_id"] = resolvedDefaultID
				resp["user_default_template_version"] = resolvedDefaultVersion
			}
			deps.WriteJSON(w, http.StatusOK, resp)
		case http.MethodPost:
			http.Error(w, "template mutation is not supported by task-orchestrator", http.StatusNotImplemented)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
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
		if deps.ReadModel == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "template mutation is not supported by task-orchestrator", http.StatusNotImplemented)
			return
		}
		row, err := deps.ReadModel.GetAccessibleTemplate(r.Context(), deps.UserID(r), templateID)
		if err != nil {
			if err == pgx.ErrNoRows {
				http.Error(w, "template not found", http.StatusNotFound)
				return
			}
			http.Error(w, "failed to load template", http.StatusInternalServerError)
			return
		}
		isResolvedDefault := false
		if resolved, err := deps.ReadModel.GetResolvedDefaultTemplate(r.Context(), deps.UserID(r)); err == nil && resolved != nil {
			isResolvedDefault = strings.TrimSpace(resolved.DefaultTemplateID) == row.TemplateID
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"template_id":       row.TemplateID,
			"name":              row.Name,
			"description":       row.Description,
			"scope":             row.Scope,
			"owner_user_id":     row.OwnerUserID,
			"status":            row.Status,
			"is_default":        isResolvedDefault,
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
		reqTemplateID := strings.TrimSpace(StringOrDefault(payload["template_id"], ""))
		reqVersion := IntOrDefault(payload["version"], 0)
		reqFront := StringOrDefault(payload["front_html"], "")
		reqBack := StringOrDefault(payload["back_html"], "")
		reqCSS := StringOrDefault(payload["css"], "")
		reqJS := StringOrDefault(payload["js"], "")

		templateID := reqTemplateID
		templateVersion := reqVersion
		if templateVersion <= 0 {
			templateVersion = 1
		}
		var templateMappingSpec map[string]any
		availableProfiles := []string{}
		defaultProfile := ""
		if reqTemplateID != "" {
			if deps.ReadModel == nil {
				http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
				return
			}
			tpl, err := deps.ReadModel.GetAccessibleTemplate(r.Context(), deps.UserID(r), reqTemplateID)
			if err != nil {
				if err == pgx.ErrNoRows {
					http.Error(w, "template not found", http.StatusNotFound)
					return
				}
				http.Error(w, "failed to load template", http.StatusInternalServerError)
				return
			}
			templateID = tpl.TemplateID
			templateVersion = tpl.LatestVersion
			templateMappingSpec = tpl.MappingSpec
			availableProfiles, defaultProfile = ExtractTemplateProfiles(tpl.MappingSpec)
			if reqFront == "" {
				reqFront = tpl.FrontHTML
			}
			if reqBack == "" {
				reqBack = tpl.BackHTML
			}
			if reqCSS == "" {
				reqCSS = tpl.CSS
			}
			if reqJS == "" {
				reqJS = tpl.JS
			}
		}
		if strings.TrimSpace(reqFront) == "" || strings.TrimSpace(reqBack) == "" {
			http.Error(w, "front_html and back_html are required", http.StatusBadRequest)
			return
		}

		proxyPayload := map[string]any{
			"template_id":      templateID,
			"version":          templateVersion,
			"front_html":       reqFront,
			"back_html":        reqBack,
			"css":              reqCSS,
			"js":               reqJS,
			"sample_fields":    payload["sample_fields"],
			"template_profile": StringOrDefault(payload["template_profile"], ""),
			"card_type":        StringOrDefault(payload["card_type"], ""),
			"preview_mode":     StringOrDefault(payload["preview_mode"], "high_fidelity"),
			"render_target":    StringOrDefault(payload["render_target"], "anki"),
			"mapping_spec":     payload["mapping_spec"],
		}
		if len(templateMappingSpec) > 0 {
			proxyPayload["mapping_spec"] = templateMappingSpec
		}
		if strings.TrimSpace(StringOrDefault(payload["template_profile"], "")) == "" && defaultProfile != "" {
			proxyPayload["template_profile"] = defaultProfile
		}
		if sample, ok := ResolveSampleFieldsFromMapping(templateMappingSpec, strings.TrimSpace(StringOrDefault(proxyPayload["template_profile"], ""))); ok {
			if _, exists := proxyPayload["sample_fields"]; !exists || MapFromAny(proxyPayload["sample_fields"]) == nil {
				proxyPayload["sample_fields"] = sample
			}
		}
		body, statusCode, err := ProxyJSON(r.Context(), deps.HTTPClient, deps.AnkiRuntimeURL, "/internal/anki/preview", proxyPayload)
		if err != nil {
			http.Error(w, "anki runtime preview unavailable", http.StatusBadGateway)
			return
		}
		if statusCode < 200 || statusCode >= 300 {
			w.WriteHeader(statusCode)
			_, _ = w.Write(body)
			return
		}
		var previewResp map[string]any
		if err := json.Unmarshal(body, &previewResp); err != nil {
			deps.WriteRawJSON(w, statusCode, body)
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
		deps.WriteJSON(w, statusCode, previewResp)
	}
}

func NewCardTemplateValidateHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback("/internal/anki/validate-template", deps, true)
}

func NewCardTemplateRequiredFieldsHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback("/internal/anki/required-fields", deps, false)
}

func NewCardTemplatePrecheckHandler(deps TemplatesDeps) http.HandlerFunc {
	return templateProxyWithTemplateFallback("/internal/anki/precheck", deps, false)
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
		body, statusCode, err := ProxyJSON(r.Context(), deps.HTTPClient, deps.AnkiRuntimeURL, "/internal/anki/build-apkg", payload)
		if err != nil {
			http.Error(w, "anki runtime build-apkg unavailable", http.StatusBadGateway)
			return
		}
		if statusCode < 200 || statusCode >= 300 {
			w.WriteHeader(statusCode)
			_, _ = w.Write(body)
			return
		}
		deps.WriteRawJSON(w, statusCode, body)
	}
}

func NewUserTemplatePreferencesHandler(deps TemplatesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.ReadModel == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := deps.UserID(r)
		switch r.Method {
		case http.MethodGet:
			pref, err := deps.ReadModel.GetResolvedDefaultTemplate(r.Context(), userID)
			if err != nil {
				if err == pgx.ErrNoRows {
					http.Error(w, "no default template configured", http.StatusNotFound)
					return
				}
				http.Error(w, "failed to load user template preference", http.StatusInternalServerError)
				return
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{
				"user_id":                  userID,
				"default_template_id":      pref.DefaultTemplateID,
				"default_template_version": pref.DefaultTemplateVersion,
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
			if err := deps.ReadModel.UpsertUserTemplatePreference(r.Context(), userID, req.DefaultTemplateID, req.DefaultTemplateVersion); err != nil {
				http.Error(w, "failed to update user template preference", http.StatusInternalServerError)
				return
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{
				"user_id":                  userID,
				"default_template_id":      req.DefaultTemplateID,
				"default_template_version": req.DefaultTemplateVersion,
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
	if deps.ReadModel == nil {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	row, err := deps.ReadModel.GetAccessibleTemplate(r.Context(), deps.UserID(r), templateID)
	if err != nil {
		if err == pgx.ErrNoRows {
			http.Error(w, "template not found", http.StatusNotFound)
			return
		}
		http.Error(w, "failed to load template", http.StatusInternalServerError)
		return
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"schema_version": "kctpl/v1",
		"exported_at":    deps.NowRFC3339(),
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
		},
		"version": map[string]any{
			"template_id":  row.TemplateID,
			"version":      row.LatestVersion,
			"front_html":   row.FrontHTML,
			"back_html":    row.BackHTML,
			"css":          row.CSS,
			"js":           row.JS,
			"is_published": row.VersionPublished,
			"mapping_spec": row.MappingSpec,
		},
	})
}

func templateProxyWithTemplateFallback(path string, deps TemplatesDeps, withJS bool) http.HandlerFunc {
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
		templateID := strings.TrimSpace(StringOrDefault(payload["template_id"], ""))
		if templateID != "" {
			if deps.ReadModel == nil {
				http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
				return
			}
			tpl, err := deps.ReadModel.GetAccessibleTemplate(r.Context(), deps.UserID(r), templateID)
			if err != nil {
				if err == pgx.ErrNoRows {
					http.Error(w, "template not found", http.StatusNotFound)
					return
				}
				http.Error(w, "failed to load template", http.StatusInternalServerError)
				return
			}
			if StringOrDefault(payload["front_html"], "") == "" {
				payload["front_html"] = tpl.FrontHTML
			}
			if StringOrDefault(payload["back_html"], "") == "" {
				payload["back_html"] = tpl.BackHTML
			}
			if StringOrDefault(payload["css"], "") == "" {
				payload["css"] = tpl.CSS
			}
			if withJS {
				if _, ok := payload["js"]; !ok || StringOrDefault(payload["js"], "") == "" {
					payload["js"] = tpl.JS
				}
				payload["version"] = tpl.LatestVersion
			}
		}
		if strings.TrimSpace(StringOrDefault(payload["front_html"], "")) == "" || strings.TrimSpace(StringOrDefault(payload["back_html"], "")) == "" {
			http.Error(w, "front_html and back_html are required", http.StatusBadRequest)
			return
		}
		body, statusCode, err := ProxyJSON(r.Context(), deps.HTTPClient, deps.AnkiRuntimeURL, path, payload)
		if err != nil {
			http.Error(w, "anki runtime unavailable", http.StatusBadGateway)
			return
		}
		if statusCode < 200 || statusCode >= 300 {
			w.WriteHeader(statusCode)
			_, _ = w.Write(body)
			return
		}
		deps.WriteRawJSON(w, statusCode, body)
	}
}
