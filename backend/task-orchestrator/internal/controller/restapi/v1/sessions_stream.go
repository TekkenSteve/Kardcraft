package v1

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

func handleSessionStreamState(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	snapshot, ok := loadConversationSnapshot(w, r, sessionID, deps)
	if !ok {
		return
	}
	deps.WriteJSON(w, http.StatusOK, snapshot)
}

func handleSessionEvents(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	userID, ok := authorizeConversationSession(w, r, sessionID, deps)
	if !ok {
		return
	}
	after := int64(0)
	rawCursor := strings.TrimSpace(r.URL.Query().Get("after"))
	if rawCursor == "" {
		rawCursor = strings.TrimSpace(r.Header.Get("Last-Event-ID"))
	}
	if rawCursor != "" {
		parsed, err := strconv.ParseInt(rawCursor, 10, 64)
		if err != nil || parsed < 0 {
			http.Error(w, "after must be a non-negative sequence", http.StatusBadRequest)
			return
		}
		after = parsed
	}
	subscription, err := deps.Conversation.SubscribeThread(r.Context(), usecase.ConversationStreamScope{
		ThreadID: sessionID, AccountID: userID, ProjectID: sessionID, AfterSequence: after,
	})
	if err != nil {
		writeConversationError(w, err)
		return
	}
	defer subscription.Close()
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	fmt.Fprint(w, ": connected\n\n")
	flusher.Flush()
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
			fmt.Fprintf(w, ": ping %d\n\n", time.Now().UTC().Unix())
			flusher.Flush()
		case event, open := <-subscription.Events():
			if !open {
				return
			}
			encoded, err := json.Marshal(event)
			if err != nil {
				continue
			}
			fmt.Fprintf(w, "id: %d\n", event.Sequence)
			fmt.Fprintf(w, "event: %s\n", event.EventType)
			fmt.Fprintf(w, "data: %s\n\n", encoded)
			flusher.Flush()
		}
	}
}

func handleSessionRuns(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	userID, ok := authorizeConversationSession(w, r, sessionID, deps)
	if !ok {
		return
	}
	if deps.CommandService == nil {
		http.Error(w, "conversation commands unavailable", http.StatusServiceUnavailable)
		return
	}
	var body struct {
		Content         string           `json:"content"`
		InterruptID     string           `json:"interrupt_id"`
		Attachments     []map[string]any `json:"attachments"`
		Metadata        map[string]any   `json:"metadata"`
		Context         map[string]any   `json:"context"`
		ContextEnvelope map[string]any   `json:"context_envelope"`
	}
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil {
		http.Error(w, "invalid run body", http.StatusBadRequest)
		return
	}
	idempotencyKey := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if idempotencyKey == "" {
		http.Error(w, "Idempotency-Key header is required", http.StatusBadRequest)
		return
	}
	result, err := deps.CommandService.SendMessageToSession(r.Context(), usecase.SessionMessageCommand{
		SessionID: sessionID, UserID: userID, Content: strings.TrimSpace(body.Content),
		Attachments: body.Attachments, Context: body.Context, ContextEnvelope: body.ContextEnvelope,
		InterruptID: strings.TrimSpace(body.InterruptID), IdempotencyKey: idempotencyKey,
		Metadata: body.Metadata, SentAt: time.Now().UTC(),
	})
	if err != nil {
		if errors.Is(err, usecase.ErrConversationInterruptRequired) || errors.Is(err, usecase.ErrConversationInterruptMismatch) {
			http.Error(w, err.Error(), http.StatusConflict)
			return
		}
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	deps.WriteJSON(w, http.StatusAccepted, result)
}

func loadConversationSnapshot(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) (usecase.ConversationThreadSnapshot, bool) {
	userID, ok := authorizeConversationSession(w, r, sessionID, deps)
	if !ok {
		return usecase.ConversationThreadSnapshot{}, false
	}
	snapshot, err := deps.Conversation.GetThreadSnapshot(r.Context(), usecase.ConversationThreadScope{
		ThreadID: sessionID, AccountID: userID, ProjectID: sessionID, EventLimit: 500,
	})
	if err != nil {
		writeConversationError(w, err)
		return usecase.ConversationThreadSnapshot{}, false
	}
	return snapshot, true
}

func authorizeConversationSession(w http.ResponseWriter, r *http.Request, sessionID string, deps SessionsDeps) (string, bool) {
	if deps.Conversation == nil || deps.ReadModel == nil || !deps.ReadModel.Ready() {
		http.Error(w, "conversation storage unavailable", http.StatusServiceUnavailable)
		return "", false
	}
	userID := deps.UserID(r)
	if _, err := deps.ReadModel.GetSession(r.Context(), sessionID, userID); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return "", false
	}
	return userID, true
}

func writeConversationError(w http.ResponseWriter, err error) {
	if errors.Is(err, usecase.ErrConversationThreadNotFound) {
		http.Error(w, "conversation thread not found", http.StatusNotFound)
		return
	}
	if errors.Is(err, usecase.ErrConversationTenantMismatch) {
		http.Error(w, "conversation access denied", http.StatusForbidden)
		return
	}
	http.Error(w, "conversation storage error", http.StatusInternalServerError)
}
