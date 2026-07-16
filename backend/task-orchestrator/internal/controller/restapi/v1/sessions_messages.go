package v1

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

type SessionMessageHTTPBody struct {
	Content         string         `json:"content"`
	Attachments     []Attachment   `json:"attachments,omitempty"`
	FileIDs         []string       `json:"file_ids,omitempty"`
	Context         map[string]any `json:"context,omitempty"`
	ContextEnvelope map[string]any `json:"context_envelope,omitempty"`
	Metadata        map[string]any `json:"metadata,omitempty"`
	IdempotencyKey  string         `json:"idempotency_key,omitempty"`
}

func handleSessionMessages(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !deps.IsTaskExecutionAvailable() {
		http.Error(w, "task execution unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.CommandService == nil {
		http.Error(w, "command service unavailable", http.StatusServiceUnavailable)
		return
	}
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
		return
	}

	var req SessionMessageHTTPBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	content := strings.TrimSpace(req.Content)
	attachments := normalizeInputAttachments(req.Attachments)
	fileIDs := dedupeFileIDs(req.FileIDs)
	if content == "" && len(attachments) == 0 && len(fileIDs) == 0 {
		http.Error(w, "content or attachments are required", http.StatusBadRequest)
		return
	}

	userID := deps.UserID(r)
	idempotencyKey, err := ensureCorrelationID(req.IdempotencyKey)
	if err != nil {
		http.Error(w, "failed to generate idempotency_key", http.StatusInternalServerError)
		return
	}
	if req.ContextEnvelope == nil {
		req.ContextEnvelope = map[string]any{}
	}
	req.ContextEnvelope["correlation_id"] = idempotencyKey
	sentAt := time.Now().UTC()
	result, err := deps.CommandService.SendMessageToSession(r.Context(), usecase.SessionMessageCommand{
		SessionID:       sessionID,
		UserID:          userID,
		Content:         content,
		Attachments:     attachments,
		FileIDs:         fileIDs,
		Context:         req.Context,
		ContextEnvelope: req.ContextEnvelope,
		Metadata:        req.Metadata,
		IdempotencyKey:  idempotencyKey,
		SentAt:          sentAt,
	})
	if err != nil {
		if errors.Is(err, usecase.ErrNoActiveTask) {
			deps.WriteAPIError(w, http.StatusConflict, deps.ActiveTaskCode, "session has no active task", map[string]any{"session_id": sessionID})
			return
		}
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	deps.WriteJSON(w, http.StatusAccepted, map[string]any{
		"session_id":      result.SessionID,
		"active_task_id":  result.ActiveTaskID,
		"idempotency_key": result.IdempotencyKey,
		"sent_at":         result.SentAt.Format(time.RFC3339),
		"stream_id":       result.StreamID,
	})
}
