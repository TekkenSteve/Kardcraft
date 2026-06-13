package restapi

import (
	"encoding/json"
	"net/http"
	"strings"
)

func handleSessionWorkspace(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}
	resp, err := deps.ReadModel.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	normalized := NormalizeWorkspaceResponse(resp, sessionID)

	needTemplateMetadata := true
	if templateID, ok := normalized["template_id"].(string); ok && strings.TrimSpace(templateID) != "" {
		if supported := normalizeStringSliceAny(normalized["supported_question_types"]); len(supported) > 0 {
			needTemplateMetadata = false
		}
	}
	if needTemplateMetadata {
		tasks, err := deps.ReadModel.ListSessionTasks(r.Context(), sessionID, userID)
		if err == nil {
			for i := len(tasks) - 1; i >= 0; i-- {
				task := tasks[i]
				resultMap, ok := normalizeResultObject(task.Result)
				if !ok || len(resultMap) == 0 {
					continue
				}
				metadata, ok := resultMap["metadata"].(map[string]any)
				if !ok || len(metadata) == 0 {
					continue
				}
				templateID := strings.TrimSpace(asStringAny(metadata["template_id"]))
				if templateID == "" {
					continue
				}
				normalized["template_id"] = templateID
				if supported := normalizeStringSliceAny(metadata["supported_question_types"]); len(supported) > 0 {
					normalized["supported_question_types"] = supported
				}
				selected := strings.TrimSpace(asStringAny(metadata["selected_question_type"]))
				if selected != "" {
					normalized["selected_question_type"] = selected
				}
				break
			}
		}
	}

	deps.WriteJSON(w, http.StatusOK, normalized)
}

func normalizeResultObject(raw any) (map[string]any, bool) {
	if raw == nil {
		return nil, false
	}
	if m, ok := raw.(map[string]any); ok {
		return m, true
	}
	switch v := raw.(type) {
	case []byte:
		var out map[string]any
		if err := json.Unmarshal(v, &out); err == nil && len(out) > 0 {
			return out, true
		}
	case string:
		s := strings.TrimSpace(v)
		if s == "" {
			return nil, false
		}
		var out map[string]any
		if err := json.Unmarshal([]byte(s), &out); err == nil && len(out) > 0 {
			return out, true
		}
	}
	return nil, false
}
