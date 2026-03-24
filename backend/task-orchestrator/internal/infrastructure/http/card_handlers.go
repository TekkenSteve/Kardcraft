package httpserver

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

func (s *Server) cardsHandler(w http.ResponseWriter, r *http.Request) {
	trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/cards/"), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) < 2 {
		http.NotFound(w, r)
		return
	}
	sessionID := parts[0]
	action := parts[len(parts)-1]
	switch action {
	case "bulk":
		s.handleBulkCards(w, r, sessionID)
	case "lock":
		if len(parts) != 3 {
			http.Error(w, "invalid path format", http.StatusBadRequest)
			return
		}
		s.handleCardLock(w, r, sessionID, parts[1])
	case "edit":
		if len(parts) != 3 {
			http.Error(w, "invalid path format", http.StatusBadRequest)
			return
		}
		s.handleCardEdit(w, r, sessionID, parts[1])
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) handleBulkCards(w http.ResponseWriter, r *http.Request, sessionID string) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Action  string   `json:"action"`
		CardIDs []string `json:"card_ids"`
		Status  string   `json:"status"`
		Model   string   `json:"model"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if len(req.CardIDs) == 0 {
		http.Error(w, "card_ids required", http.StatusBadRequest)
		return
	}
	if req.Action != "update_status" && req.Action != "update_model" {
		http.Error(w, "invalid action", http.StatusBadRequest)
		return
	}
	if req.Action == "update_status" {
		if req.Status != "draft" && req.Status != "ai_editing" && req.Status != "user_editing" && req.Status != "confirmed" {
			http.Error(w, "invalid status", http.StatusBadRequest)
			return
		}
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	workspace, err := s.sessionDB.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	workspace = normalizeWorkspaceResponse(workspace, sessionID)
	cards := extractWorkspaceCards(workspace)
	now := time.Now().UTC().Format(time.RFC3339)
	idSet := make(map[string]struct{}, len(req.CardIDs))
	for _, id := range req.CardIDs {
		idSet[id] = struct{}{}
	}
	updated := 0
	for _, card := range cards {
		cardID, _ := card["card_id"].(string)
		if _, ok := idSet[cardID]; !ok {
			continue
		}
		content, _ := card["content"].(map[string]any)
		if content == nil {
			content = map[string]any{"version": 1, "model": "default", "data": map[string]any{"front": "", "back": ""}}
			card["content"] = content
		}
		editState, _ := card["edit_state"].(map[string]any)
		if editState == nil {
			editState = map[string]any{"status": "draft"}
			card["edit_state"] = editState
		}
		meta, _ := card["meta"].(map[string]any)
		if meta == nil {
			meta = map[string]any{"created_at": now, "modified_at": now, "manual_edits": 0}
			card["meta"] = meta
		}
		switch req.Action {
		case "update_status":
			editState["status"] = req.Status
		case "update_model":
			content["model"] = req.Model
		}
		meta["modified_at"] = now
		updated++
	}
	workspace["cards"] = cards
	workspace["card_count"] = len(cards)
	workspace["status"] = "active"
	workspace["version"] = workspaceVersion(workspace) + 1
	if err := s.sessionDB.SaveWorkspace(r.Context(), sessionID, workspace); err != nil {
		http.Error(w, "failed to save workspace", http.StatusInternalServerError)
		return
	}
	_ = s.sessionDB.MarkSessionActive(r.Context(), sessionID, userID)
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "updated": updated, "user_id": userID})
}

func (s *Server) handleCardLock(w http.ResponseWriter, r *http.Request, sessionID, cardID string) {
	if r.Method != http.MethodPost && r.Method != http.MethodDelete {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := userIDFromContext(r.Context())
	holder := fmt.Sprintf("user:%s", userID)
	now := time.Now().UTC()
	workspace, err := s.sessionDB.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	workspace = normalizeWorkspaceResponse(workspace, sessionID)
	cards := extractWorkspaceCards(workspace)
	found := false
	for _, card := range cards {
		if id, _ := card["card_id"].(string); id != cardID {
			continue
		}
		editState, _ := card["edit_state"].(map[string]any)
		if editState == nil {
			editState = map[string]any{"status": "draft"}
			card["edit_state"] = editState
		}
		switch r.Method {
		case http.MethodPost:
			lockedBy, _ := editState["locked_by"].(string)
			if lockedBy != "" && lockedBy != holder {
				http.Error(w, "card is locked by another user", http.StatusConflict)
				return
			}
			editState["locked_by"] = holder
			editState["locked_at"] = now.Format(time.RFC3339)
			found = true
		case http.MethodDelete:
			lockedBy, _ := editState["locked_by"].(string)
			if lockedBy != holder {
				http.Error(w, "lock not found or held by another user", http.StatusNotFound)
				return
			}
			delete(editState, "locked_by")
			delete(editState, "locked_at")
			delete(editState, "expires_at")
			found = true
		}
		break
	}
	if !found {
		http.Error(w, "card not found", http.StatusNotFound)
		return
	}
	workspace["cards"] = cards
	workspace["card_count"] = len(cards)
	workspace["version"] = workspaceVersion(workspace) + 1
	workspace["status"] = "active"
	if err := s.sessionDB.SaveWorkspace(r.Context(), sessionID, workspace); err != nil {
		http.Error(w, "failed to save workspace", http.StatusInternalServerError)
		return
	}
	_ = s.sessionDB.MarkSessionActive(r.Context(), sessionID, userID)
	if r.Method == http.MethodDelete {
		writeJSON(w, http.StatusOK, map[string]any{"success": true, "card_id": cardID, "released": true})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "card_id": cardID, "locked_by": holder})
}

func (s *Server) handleCardEdit(w http.ResponseWriter, r *http.Request, sessionID, cardID string) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if s.sessionDB == nil || !s.sessionDB.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	var req struct {
		Content     map[string]any `json:"content"`
		BaseVersion int            `json:"base_version"`
	}
	if err := parseJSON(r, &req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if req.Content == nil {
		http.Error(w, "content is required", http.StatusBadRequest)
		return
	}
	userID := userIDFromContext(r.Context())
	now := time.Now().UTC().Format(time.RFC3339)
	workspace, err := s.sessionDB.LoadWorkspace(r.Context(), sessionID)
	if err != nil {
		http.Error(w, "failed to load workspace", http.StatusInternalServerError)
		return
	}
	workspace = normalizeWorkspaceResponse(workspace, sessionID)
	cards := extractWorkspaceCards(workspace)
	found := false
	newVersion := 0
	for _, card := range cards {
		if id, _ := card["card_id"].(string); id != cardID {
			continue
		}
		content, _ := card["content"].(map[string]any)
		if content == nil {
			content = map[string]any{"version": 1, "model": "default", "data": map[string]any{"front": "", "back": ""}}
			card["content"] = content
		}
		version := intFromAny(content["version"])
		if req.BaseVersion > 0 && version != req.BaseVersion {
			http.Error(w, fmt.Sprintf("version mismatch: expected %d, got %d", req.BaseVersion, version), http.StatusConflict)
			return
		}
		content["data"] = req.Content
		content["version"] = version + 1
		newVersion = version + 1
		editState, _ := card["edit_state"].(map[string]any)
		if editState == nil {
			editState = map[string]any{}
			card["edit_state"] = editState
		}
		editState["status"] = "user_editing"
		meta, _ := card["meta"].(map[string]any)
		if meta == nil {
			meta = map[string]any{"created_at": now, "modified_at": now, "manual_edits": 0}
			card["meta"] = meta
		}
		meta["modified_at"] = now
		meta["manual_edits"] = intFromAny(meta["manual_edits"]) + 1
		found = true
		break
	}
	if !found {
		http.Error(w, "card not found", http.StatusNotFound)
		return
	}
	workspace["cards"] = cards
	workspace["card_count"] = len(cards)
	workspace["version"] = workspaceVersion(workspace) + 1
	workspace["status"] = "active"
	if err := s.sessionDB.SaveWorkspace(r.Context(), sessionID, workspace); err != nil {
		http.Error(w, "failed to save workspace", http.StatusInternalServerError)
		return
	}
	_ = s.sessionDB.MarkSessionActive(r.Context(), sessionID, userID)
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "card_id": cardID, "new_version": newVersion})
}

func extractWorkspaceCards(workspace map[string]any) []map[string]any {
	raw, _ := workspace["cards"].([]any)
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		card, ok := item.(map[string]any)
		if ok {
			out = append(out, card)
		}
	}
	return out
}

func intFromAny(v any) int {
	switch typed := v.(type) {
	case int:
		return typed
	case int32:
		return int(typed)
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	default:
		return 0
	}
}

func workspaceVersion(workspace map[string]any) int {
	return intFromAny(workspace["version"])
}
