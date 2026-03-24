package httpserver

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

func (s *Server) cardTemplatesHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if s.sessionDB == nil {
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
		userID := userIDFromContext(r.Context())
		rows, total, err := s.sessionDB.ListAccessibleTemplates(r.Context(), userID, limit, offset)
		if err != nil {
			http.Error(w, "failed to list templates", http.StatusInternalServerError)
			return
		}
		list := make([]*CardTemplate, 0, len(rows))
		for _, row := range rows {
			list = append(list, &CardTemplate{
				TemplateID:       row.TemplateID,
				Name:             row.Name,
				Description:      row.Description,
				Scope:            row.Scope,
				OwnerUserID:      row.OwnerUserID,
				Status:           row.Status,
				IsDefault:        row.IsDefault,
				LatestVersion:    row.LatestVersion,
				VersionPublished: row.VersionPublished,
				CreatedAt:        row.CreatedAt.UTC().Format(time.RFC3339),
				UpdatedAt:        row.UpdatedAt.UTC().Format(time.RFC3339),
			})
		}
		resp := map[string]any{"templates": list, "total_count": total}
		if pref, err := s.sessionDB.GetUserTemplatePreference(r.Context(), userID); err == nil {
			resp["user_default_template_id"] = pref.DefaultTemplateID
			resp["user_default_template_version"] = pref.DefaultTemplateVersion
		}
		writeJSON(w, http.StatusOK, resp)
	case http.MethodPost:
		http.Error(w, "template mutation is not supported by task-orchestrator", http.StatusNotImplemented)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) cardTemplateDetailHandler(w http.ResponseWriter, r *http.Request) {
	trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/card-templates/"), "/")
	if trimmed == "" {
		http.NotFound(w, r)
		return
	}
	parts := strings.Split(trimmed, "/")
	templateID := parts[0]
	if len(parts) > 1 && parts[1] == "export" {
		s.handleTemplateExport(w, r, templateID)
		return
	}
	if s.sessionDB == nil {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "template mutation is not supported by task-orchestrator", http.StatusNotImplemented)
		return
	}
	row, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), templateID)
	if err != nil {
		if err == pgx.ErrNoRows {
			http.Error(w, "template not found", http.StatusNotFound)
			return
		}
		http.Error(w, "failed to load template", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, CardTemplate{
		TemplateID:       row.TemplateID,
		Name:             row.Name,
		Description:      row.Description,
		Scope:            row.Scope,
		OwnerUserID:      row.OwnerUserID,
		Status:           row.Status,
		IsDefault:        row.IsDefault,
		LatestVersion:    row.LatestVersion,
		VersionPublished: row.VersionPublished,
		CreatedAt:        row.CreatedAt.UTC().Format(time.RFC3339),
		UpdatedAt:        row.UpdatedAt.UTC().Format(time.RFC3339),
	})
}

func (s *Server) handleTemplateExport(w http.ResponseWriter, r *http.Request, templateID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	row, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), templateID)
	if err != nil {
		if err == pgx.ErrNoRows {
			http.Error(w, "template not found", http.StatusNotFound)
			return
		}
		http.Error(w, "failed to load template", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version": "kctpl/v1",
		"exported_at":    nowRFC3339(),
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

func (s *Server) cardTemplatePreviewHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	payload := map[string]any{}
	if err := parseJSON(r, &payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	reqTemplateID := strings.TrimSpace(stringOrDefault(payload["template_id"], ""))
	reqVersion := intOrDefault(payload["version"], 0)
	reqFront := stringOrDefault(payload["front_html"], "")
	reqBack := stringOrDefault(payload["back_html"], "")
	reqCSS := stringOrDefault(payload["css"], "")
	reqJS := stringOrDefault(payload["js"], "")

	templateID := reqTemplateID
	templateVersion := reqVersion
	if templateVersion <= 0 {
		templateVersion = 1
	}
	var templateMappingSpec map[string]any
	availableProfiles := []string{}
	defaultProfile := ""

	if reqTemplateID != "" {
		if s.sessionDB == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		tpl, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), reqTemplateID)
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
		availableProfiles, defaultProfile = extractTemplateProfiles(tpl.MappingSpec)
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
		"template_profile": stringOrDefault(payload["template_profile"], ""),
		"card_type":        stringOrDefault(payload["card_type"], ""),
		"preview_mode":     stringOrDefault(payload["preview_mode"], "high_fidelity"),
		"render_target":    stringOrDefault(payload["render_target"], "anki"),
		"mapping_spec":     payload["mapping_spec"],
	}
	if len(templateMappingSpec) > 0 {
		proxyPayload["mapping_spec"] = templateMappingSpec
	}
	if strings.TrimSpace(stringOrDefault(payload["template_profile"], "")) == "" && defaultProfile != "" {
		proxyPayload["template_profile"] = defaultProfile
	}
	if sample, ok := resolveSampleFieldsFromMapping(
		templateMappingSpec,
		strings.TrimSpace(stringOrDefault(proxyPayload["template_profile"], "")),
	); ok {
		if _, exists := proxyPayload["sample_fields"]; !exists || mapFromAny(proxyPayload["sample_fields"]) == nil {
			proxyPayload["sample_fields"] = sample
		}
	}

	body, statusCode, err := s.proxyJSONToAnkiRuntime(r.Context(), "/internal/anki/preview", proxyPayload)
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
		writeRawJSON(w, statusCode, body)
		return
	}
	if _, ok := previewResp["available_profiles"]; !ok || len(stringSliceFromAny(previewResp["available_profiles"])) == 0 {
		if len(availableProfiles) > 0 {
			previewResp["available_profiles"] = availableProfiles
		}
	}
	if profile := strings.TrimSpace(stringOrDefault(previewResp["template_profile"], "")); profile == "" {
		if selected := strings.TrimSpace(stringOrDefault(proxyPayload["template_profile"], "")); selected != "" {
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
	writeJSON(w, statusCode, previewResp)
}

func (s *Server) cardTemplateValidateHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	payload := map[string]any{}
	if err := parseJSON(r, &payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	templateID := strings.TrimSpace(stringOrDefault(payload["template_id"], ""))
	if templateID != "" {
		if s.sessionDB == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		tpl, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), templateID)
		if err != nil {
			if err == pgx.ErrNoRows {
				http.Error(w, "template not found", http.StatusNotFound)
				return
			}
			http.Error(w, "failed to load template", http.StatusInternalServerError)
			return
		}
		if stringOrDefault(payload["front_html"], "") == "" {
			payload["front_html"] = tpl.FrontHTML
		}
		if stringOrDefault(payload["back_html"], "") == "" {
			payload["back_html"] = tpl.BackHTML
		}
		if stringOrDefault(payload["css"], "") == "" {
			payload["css"] = tpl.CSS
		}
		if _, ok := payload["js"]; !ok || stringOrDefault(payload["js"], "") == "" {
			payload["js"] = tpl.JS
		}
		payload["version"] = tpl.LatestVersion
	}
	if strings.TrimSpace(stringOrDefault(payload["front_html"], "")) == "" || strings.TrimSpace(stringOrDefault(payload["back_html"], "")) == "" {
		http.Error(w, "front_html and back_html are required", http.StatusBadRequest)
		return
	}
	body, statusCode, err := s.proxyJSONToAnkiRuntime(r.Context(), "/internal/anki/validate-template", payload)
	if err != nil {
		http.Error(w, "anki runtime validate unavailable", http.StatusBadGateway)
		return
	}
	if statusCode < 200 || statusCode >= 300 {
		w.WriteHeader(statusCode)
		_, _ = w.Write(body)
		return
	}
	writeRawJSON(w, statusCode, body)
}

func (s *Server) cardTemplateRequiredFieldsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	payload := map[string]any{}
	if err := parseJSON(r, &payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	templateID := strings.TrimSpace(stringOrDefault(payload["template_id"], ""))
	if templateID != "" {
		if s.sessionDB == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		tpl, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), templateID)
		if err != nil {
			if err == pgx.ErrNoRows {
				http.Error(w, "template not found", http.StatusNotFound)
				return
			}
			http.Error(w, "failed to load template", http.StatusInternalServerError)
			return
		}
		if stringOrDefault(payload["front_html"], "") == "" {
			payload["front_html"] = tpl.FrontHTML
		}
		if stringOrDefault(payload["back_html"], "") == "" {
			payload["back_html"] = tpl.BackHTML
		}
		if stringOrDefault(payload["css"], "") == "" {
			payload["css"] = tpl.CSS
		}
	}
	if strings.TrimSpace(stringOrDefault(payload["front_html"], "")) == "" || strings.TrimSpace(stringOrDefault(payload["back_html"], "")) == "" {
		http.Error(w, "front_html and back_html are required", http.StatusBadRequest)
		return
	}
	body, statusCode, err := s.proxyJSONToAnkiRuntime(r.Context(), "/internal/anki/required-fields", payload)
	if err != nil {
		http.Error(w, "anki runtime required-fields unavailable", http.StatusBadGateway)
		return
	}
	if statusCode < 200 || statusCode >= 300 {
		w.WriteHeader(statusCode)
		_, _ = w.Write(body)
		return
	}
	writeRawJSON(w, statusCode, body)
}

func (s *Server) cardTemplatePrecheckHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	payload := map[string]any{}
	if err := parseJSON(r, &payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	templateID := strings.TrimSpace(stringOrDefault(payload["template_id"], ""))
	if templateID != "" {
		if s.sessionDB == nil {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		tpl, err := s.sessionDB.GetAccessibleTemplate(r.Context(), userIDFromContext(r.Context()), templateID)
		if err != nil {
			if err == pgx.ErrNoRows {
				http.Error(w, "template not found", http.StatusNotFound)
				return
			}
			http.Error(w, "failed to load template", http.StatusInternalServerError)
			return
		}
		if stringOrDefault(payload["front_html"], "") == "" {
			payload["front_html"] = tpl.FrontHTML
		}
		if stringOrDefault(payload["back_html"], "") == "" {
			payload["back_html"] = tpl.BackHTML
		}
		if stringOrDefault(payload["css"], "") == "" {
			payload["css"] = tpl.CSS
		}
	}
	if strings.TrimSpace(stringOrDefault(payload["front_html"], "")) == "" || strings.TrimSpace(stringOrDefault(payload["back_html"], "")) == "" {
		http.Error(w, "front_html and back_html are required", http.StatusBadRequest)
		return
	}
	body, statusCode, err := s.proxyJSONToAnkiRuntime(r.Context(), "/internal/anki/precheck", payload)
	if err != nil {
		http.Error(w, "anki runtime precheck unavailable", http.StatusBadGateway)
		return
	}
	if statusCode < 200 || statusCode >= 300 {
		w.WriteHeader(statusCode)
		_, _ = w.Write(body)
		return
	}
	writeRawJSON(w, statusCode, body)
}

func (s *Server) cardTemplateBuildApkgHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	payload := map[string]any{}
	if err := parseJSON(r, &payload); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	body, statusCode, err := s.proxyJSONToAnkiRuntime(r.Context(), "/internal/anki/build-apkg", payload)
	if err != nil {
		http.Error(w, "anki runtime build-apkg unavailable", http.StatusBadGateway)
		return
	}
	if statusCode < 200 || statusCode >= 300 {
		w.WriteHeader(statusCode)
		_, _ = w.Write(body)
		return
	}
	writeRawJSON(w, statusCode, body)
}

func (s *Server) userTemplatePreferencesHandler(w http.ResponseWriter, r *http.Request) {
	if s.sessionDB == nil {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	switch r.Method {
	case http.MethodGet:
		pref, err := s.sessionDB.GetUserTemplatePreference(r.Context(), userID)
		if err != nil {
			http.Error(w, "failed to load user template preference", http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, &TemplatePreference{
			UserID:                 userID,
			DefaultTemplateID:      pref.DefaultTemplateID,
			DefaultTemplateVersion: pref.DefaultTemplateVersion,
			UpdatedAt:              nowRFC3339(),
		})
	case http.MethodPost:
		var req struct {
			DefaultTemplateID      string `json:"default_template_id"`
			DefaultTemplateVersion int    `json:"default_template_version"`
		}
		if err := parseJSON(r, &req); err != nil {
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
		if err := s.sessionDB.UpsertUserTemplatePreference(r.Context(), userID, req.DefaultTemplateID, req.DefaultTemplateVersion); err != nil {
			http.Error(w, "failed to update user template preference", http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, &TemplatePreference{
			UserID:                 userID,
			DefaultTemplateID:      req.DefaultTemplateID,
			DefaultTemplateVersion: req.DefaultTemplateVersion,
			UpdatedAt:              nowRFC3339(),
		})
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}
