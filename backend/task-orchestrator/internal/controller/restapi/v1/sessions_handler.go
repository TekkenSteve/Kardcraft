package v1

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"task-orchestrator/internal/usecase"
	"time"
)

type SessionsDeps struct {
	WriteJSON     func(w http.ResponseWriter, status int, v any)
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string

	ReadModel         usecase.ReadModel
	WorkflowSvc       usecase.Workflow
	CommandService    usecase.Command
	IsTemporalEnabled func() bool

	AuthzDeniedCode string
}

func NewSessionsHandler(deps SessionsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		userID := deps.UserID(r)
		limit := 20
		offset := 0
		if raw := r.URL.Query().Get("limit"); raw != "" {
			if n, err := strconv.Atoi(raw); err == nil && n > 0 {
				limit = n
			}
		}
		if raw := r.URL.Query().Get("offset"); raw != "" {
			if n, err := strconv.Atoi(raw); err == nil && n >= 0 {
				offset = n
			}
		}
		list, total, err := deps.ReadModel.ListSessions(r.Context(), userID, limit, offset)
		if err != nil {
			http.Error(w, "failed to list sessions", http.StatusInternalServerError)
			return
		}
		sessions := make([]map[string]any, 0, len(list))
		for _, row := range list {
			sessions = append(sessions, sessionRowToResponse(row))
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{"sessions": sessions, "total_count": total})
	}
}

func NewSessionsRouter(deps SessionsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/sessions/"), "/")
		if trimmed == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(trimmed, "/")
		sessionID := parts[0]
		if len(parts) == 1 {
			handleSessionDetail(w, r, sessionID, deps)
			return
		}
		suffix := parts[1]
		switch suffix {
		case "conversation":
			handleSessionConversation(w, r, sessionID, deps)
		case "timeline":
			handleSessionTimeline(w, r, sessionID, deps)
		case "history":
			handleSessionHistory(w, r, sessionID, deps)
		case "workspace":
			handleSessionWorkspace(w, r, sessionID, deps)
		case "state":
			handleSessionState(w, r, sessionID, deps)
		default:
			http.NotFound(w, r)
		}
	}
}

func handleSessionDetail(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := deps.UserID(r)
	switch r.Method {
	case http.MethodGet:
		rec, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID)
		if err != nil || rec == nil {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, sessionRowToResponse(*rec))
	case http.MethodPatch:
		var req struct {
			Title  *string `json:"title"`
			Pinned *bool   `json:"pinned"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.Title == nil && req.Pinned == nil {
			http.Error(w, "no fields to update", http.StatusBadRequest)
			return
		}
		if err := deps.ReadModel.UpdateSessionMeta(r.Context(), sessionID, userID, req.Title, req.Pinned); err != nil {
			http.Error(w, "failed to update session", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	case http.MethodDelete:
		affected, err := deps.ReadModel.DeleteSession(r.Context(), sessionID, userID)
		if err != nil {
			http.Error(w, "failed to delete session", http.StatusInternalServerError)
			return
		}
		if affected == 0 {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func sessionRowToResponse(row usecase.SessionRow) map[string]any {
	resp := map[string]any{
		"session_id":     row.SessionID,
		"user_id":        row.UserID,
		"pinned":         row.Pinned,
		"task_count":     row.TaskCount,
		"tokens_used":    row.TokensUsed,
		"total_cost_usd": row.TotalCostUSD,
		"created_at":     row.CreatedAt.UTC().Format(time.RFC3339),
		"updated_at":     row.UpdatedAt.UTC().Format(time.RFC3339),
	}
	if row.Title != nil {
		resp["title"] = *row.Title
	}
	if row.LastActivityAt != nil {
		resp["last_activity_at"] = row.LastActivityAt.UTC().Format(time.RFC3339)
	}
	if row.LatestTaskQuery != nil {
		resp["latest_task_query"] = *row.LatestTaskQuery
	}
	if row.LatestTaskStatus != nil {
		resp["latest_task_status"] = *row.LatestTaskStatus
	}
	return resp
}
