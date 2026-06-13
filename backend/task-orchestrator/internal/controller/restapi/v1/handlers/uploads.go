package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	httpdto "task-orchestrator/internal/controller/restapi/v1/dto"
)

type UploadsDeps struct {
	WriteJSON       func(w http.ResponseWriter, status int, v any)
	NowRFC3339      func() string
	NewUploadID     func() string
	InitUpload      func(uploadID, fileName string, chunks int, sessionID string, createdAt string)
	IncrementChunk  func(uploadID string) (received int, ok bool)
	CompleteUpload  func(uploadID string, completedAt string) bool
	GetUploadStatus func(uploadID string) (map[string]any, bool)
}

func NewInitUploadHandler(deps UploadsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req httpdto.InitUploadHTTPBody
		_ = json.NewDecoder(r.Body).Decode(&req)
		uploadID := deps.NewUploadID()
		if strings.TrimSpace(uploadID) == "" {
			uploadID = fmt.Sprintf("upload_fallback_%s", deps.NowRFC3339())
		}
		fileName := strings.TrimSpace(req.FileName)
		if fileName == "" {
			fileName = "file.bin"
		}
		createdAt := deps.NowRFC3339()
		deps.InitUpload(uploadID, fileName, req.ChunkCount, strings.TrimSpace(req.SessionID), createdAt)
		deps.WriteJSON(w, http.StatusOK, map[string]any{"upload_id": uploadID, "status": "initialized"})
	}
}

func NewUploadChunkHandler(deps UploadsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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
		received, ok := deps.IncrementChunk(uploadID)
		if !ok {
			http.Error(w, "upload not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{"ok": true, "upload_id": uploadID, "received": received})
	}
}

func NewCompleteUploadHandler(deps UploadsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/files/upload/complete/"), "/")
		if ok := deps.CompleteUpload(uploadID, deps.NowRFC3339()); !ok {
			http.Error(w, "upload not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{"ok": true, "upload_id": uploadID, "file_id": fmt.Sprintf("file_%s", uploadID)})
	}
}

func NewUploadStatusHandler(deps UploadsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/files/upload/status/"), "/")
		state, ok := deps.GetUploadStatus(uploadID)
		if !ok {
			http.Error(w, "upload not found", http.StatusNotFound)
			return
		}
		deps.WriteJSON(w, http.StatusOK, state)
	}
}
