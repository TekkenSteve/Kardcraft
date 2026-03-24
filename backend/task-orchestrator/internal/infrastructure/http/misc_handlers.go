package httpserver

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

func (s *Server) handleInitFileUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req map[string]any
	_ = parseJSON(r, &req)
	uploadID := fmt.Sprintf("upload_%d", time.Now().UTC().UnixNano())
	state := &uploadState{UploadID: uploadID, Status: "initialized", FileName: stringOrDefault(req["filename"], "file.bin"), Chunks: intOrDefault(req["chunk_count"], 0), Received: 0, SessionID: stringOrDefault(req["session_id"], ""), CreatedAt: nowRFC3339()}
	s.mu.Lock()
	s.uploads[uploadID] = state
	s.mu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"upload_id": uploadID, "status": state.Status})
}

func (s *Server) handleUploadChunk(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/files/upload/chunk/"), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) < 2 {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	uploadID := parts[0]
	s.mu.Lock()
	state, ok := s.uploads[uploadID]
	if ok {
		state.Received++
		state.Status = "uploading"
	}
	s.mu.Unlock()
	if !ok {
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "upload_id": uploadID, "received": state.Received})
}

func (s *Server) handleCompleteUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/files/upload/complete/"), "/")
	s.mu.Lock()
	state, ok := s.uploads[uploadID]
	if ok {
		state.Status = "completed"
		state.CompletedAt = nowRFC3339()
	}
	s.mu.Unlock()
	if !ok {
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "upload_id": uploadID, "file_id": fmt.Sprintf("file_%s", uploadID)})
}

func (s *Server) handleGetUploadStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/files/upload/status/"), "/")
	s.mu.RLock()
	state, ok := s.uploads[uploadID]
	s.mu.RUnlock()
	if !ok {
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func (s *Server) agentsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		writeJSON(w, http.StatusOK, map[string]any{"agent_id": fmt.Sprintf("agent_%d", time.Now().UTC().Unix()), "name": "test-agent", "status": "AGENT_STATUS_ACTIVE", "message": "Agent created successfully", "created_at": nowRFC3339()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"agents": []any{}, "total_count": 0, "message": "Agent service is running"})
}

func (s *Server) rootHandler(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/api/") {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "API endpoint not found", "path": r.URL.Path, "method": r.Method})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"service": "Task Orchestrator Service", "port": s.port, "time": nowRFC3339(), "status": "running"})
}
