package v1

import (
	"encoding/json"
	"net/http"
	"strings"

	"task-orchestrator/internal/usecase"
)

type CardsDeps struct {
	WriteJSON func(w http.ResponseWriter, status int, v any)
	UserID    func(r *http.Request) string
	Workspace usecase.Workspace
}

func NewCardsHandler(deps CardsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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
			handleBulkCards(w, r, sessionID, deps)
		default:
			http.NotFound(w, r)
		}
	}
}

func handleBulkCards(w http.ResponseWriter, r *http.Request, sessionID string, deps CardsDeps) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Action       string   `json:"action"`
		CardIDs      []string `json:"card_ids"`
		Status       string   `json:"status"`
		QuestionType string   `json:"question_type"`
	}
	_ = json.NewDecoder(r.Body).Decode(&req)
	if len(req.CardIDs) == 0 {
		http.Error(w, "card_ids required", http.StatusBadRequest)
		return
	}
	if req.Action != "update_status" && req.Action != "update_question_type" {
		http.Error(w, "invalid action", http.StatusBadRequest)
		return
	}
	effectiveQuestionType := strings.TrimSpace(req.QuestionType)

	if req.Action == "update_status" {
		if req.Status != "draft" && req.Status != "ai_editing" && req.Status != "user_editing" && req.Status != "confirmed" {
			http.Error(w, "invalid status", http.StatusBadRequest)
			return
		}
	}
	if req.Action == "update_question_type" {
		if effectiveQuestionType == "" {
			http.Error(w, "question_type required", http.StatusBadRequest)
			return
		}
	}
	if deps.Workspace == nil {
		http.Error(w, "workspace service unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	result, err := deps.Workspace.BulkUpdateCards(r.Context(), usecase.BulkCardUpdateCommand{
		SessionID: sessionID, UserID: userID, Action: req.Action, CardIDs: req.CardIDs, Status: req.Status, QuestionType: effectiveQuestionType,
	})
	if err != nil {
		http.Error(w, "failed to update cards", http.StatusInternalServerError)
		return
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{"success": true, "updated": result.Updated, "user_id": userID})
}
