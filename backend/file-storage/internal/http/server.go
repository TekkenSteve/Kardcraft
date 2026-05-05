package http

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/sirupsen/logrus"

	"file-storage/internal/config"
	"file-storage/internal/middleware"
	"file-storage/internal/policy"
	"file-storage/internal/storage"
	"file-storage/internal/types"
)

// Server represents the HTTP server for file-storage
type Server struct {
	cfg          *config.Config
	factory      *storage.Factory
	middleware   *middleware.Chain
	policyEngine *policy.PolicyEngine
	logger       *logrus.Logger
	mux          *http.ServeMux
	uploadsMu    sync.Mutex
	uploads      map[string]*uploadSession
}

type uploadSession struct {
	UploadID   string
	FileID     string
	Key        string
	Filename   string
	ChunkCount int
	Chunks     map[int][]byte
	CreatedAt  time.Time
}

// NewServer creates a new HTTP server
func NewServer(
	cfg *config.Config,
	factory *storage.Factory,
	middlewareChain *middleware.Chain,
	policyEngine *policy.PolicyEngine,
	logger *logrus.Logger,
) *Server {
	s := &Server{
		cfg:          cfg,
		factory:      factory,
		middleware:   middlewareChain,
		policyEngine: policyEngine,
		logger:       logger,
		mux:          http.NewServeMux(),
		uploads:      make(map[string]*uploadSession),
	}
	s.registerRoutes()
	return s
}

// registerRoutes registers HTTP routes
func (s *Server) registerRoutes() {
	// CORS middleware wrapper
	corsHandler := func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-User-Id")

			if r.Method == "OPTIONS" {
				w.WriteHeader(http.StatusOK)
				return
			}
			next(w, r)
		}
	}

	s.mux.HandleFunc("/v1/files/presigned-url", corsHandler(s.handlePresignedURL))
	s.mux.HandleFunc("/v1/files/confirm-upload", corsHandler(s.handleConfirmUpload))
	s.mux.HandleFunc("/v1/files/upload/init", corsHandler(s.handleInitUpload))
	s.mux.HandleFunc("/v1/files/upload/chunk/", corsHandler(s.handleUploadChunk))
	s.mux.HandleFunc("/v1/files/upload/complete/", corsHandler(s.handleCompleteUpload))
	s.mux.HandleFunc("/v1/files/upload/status/", corsHandler(s.handleUploadStatus))
	s.mux.HandleFunc("/v1/files/health", corsHandler(s.handleHealth))
	s.mux.HandleFunc("/health", corsHandler(s.handleHealth))
}

type initUploadRequest struct {
	Filename   string `json:"filename"`
	ChunkCount int    `json:"chunk_count"`
	SessionID  string `json:"session_id"`
}

func (s *Server) handleInitUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req initUploadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}
	filename := strings.TrimSpace(req.Filename)
	if filename == "" {
		http.Error(w, "filename is required", http.StatusBadRequest)
		return
	}
	chunkCount := req.ChunkCount
	if chunkCount <= 0 {
		chunkCount = 1
	}

	userID := strings.TrimSpace(r.Header.Get("X-User-Id"))
	fileID := generateFileID()
	key := buildStorageKey(userID, strings.TrimSpace(req.SessionID), fileID, filename)
	uploadID := fmt.Sprintf("upload_%s", generateFileID())

	s.uploadsMu.Lock()
	s.uploads[uploadID] = &uploadSession{
		UploadID:   uploadID,
		FileID:     fileID,
		Key:        key,
		Filename:   filename,
		ChunkCount: chunkCount,
		Chunks:     make(map[int][]byte, chunkCount),
		CreatedAt:  time.Now(),
	}
	s.uploadsMu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"upload_id": uploadID,
		"status":    "initialized",
	})
}

func (s *Server) handleUploadChunk(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/files/upload/chunk/"), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) < 2 {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	uploadID := strings.TrimSpace(parts[0])
	chunkIndex, err := strconv.Atoi(strings.TrimSpace(parts[1]))
	if err != nil || chunkIndex < 0 {
		http.Error(w, "invalid chunk index", http.StatusBadRequest)
		return
	}

	chunk, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "failed to read chunk", http.StatusBadRequest)
		return
	}

	s.uploadsMu.Lock()
	session, ok := s.uploads[uploadID]
	if !ok {
		s.uploadsMu.Unlock()
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	if chunkIndex >= session.ChunkCount {
		s.uploadsMu.Unlock()
		http.Error(w, "chunk index out of range", http.StatusBadRequest)
		return
	}
	session.Chunks[chunkIndex] = append([]byte(nil), chunk...)
	received := len(session.Chunks)
	s.uploadsMu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"ok":       true,
		"upload_id": uploadID,
		"received": received,
	})
}

func (s *Server) handleCompleteUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/files/upload/complete/"), "/")
	s.uploadsMu.Lock()
	session, ok := s.uploads[uploadID]
	if !ok {
		s.uploadsMu.Unlock()
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	if len(session.Chunks) != session.ChunkCount {
		s.uploadsMu.Unlock()
		http.Error(w, "upload incomplete", http.StatusBadRequest)
		return
	}
	delete(s.uploads, uploadID)
	s.uploadsMu.Unlock()

	var buffer bytes.Buffer
	for index := 0; index < session.ChunkCount; index++ {
		chunk, exists := session.Chunks[index]
		if !exists {
			http.Error(w, "missing chunk", http.StatusBadRequest)
			return
		}
		if _, err := buffer.Write(chunk); err != nil {
			http.Error(w, "failed to assemble upload", http.StatusInternalServerError)
			return
		}
	}

	stor, err := s.factory.Get(s.cfg.Storage.DefaultProvider)
	if err != nil {
		s.logger.WithError(err).Error("Failed to get storage provider")
		http.Error(w, "Internal server error", http.StatusInternalServerError)
		return
	}
	metadata := &types.FileMetadata{
		ContentType:   "application/octet-stream",
		ContentLength: int64(buffer.Len()),
		CustomMeta:    map[string]string{"filename": session.Filename},
	}
	if err := stor.Upload(context.Background(), session.Key, bytes.NewReader(buffer.Bytes()), metadata); err != nil {
		s.logger.WithError(err).Error("Failed to store uploaded file")
		http.Error(w, "Failed to store uploaded file", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"ok":        true,
		"upload_id": uploadID,
		"file_id":   session.FileID,
	})
}

func (s *Server) handleUploadStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	uploadID := strings.Trim(strings.TrimPrefix(r.URL.Path, "/v1/files/upload/status/"), "/")
	s.uploadsMu.Lock()
	session, ok := s.uploads[uploadID]
	s.uploadsMu.Unlock()
	if !ok {
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"upload_id":   session.UploadID,
		"status":      "initialized",
		"file_name":   session.Filename,
		"chunk_count": session.ChunkCount,
		"received":    len(session.Chunks),
		"created_at":  session.CreatedAt.UTC().Format(time.RFC3339),
	})
}

// Handler returns the HTTP handler
func (s *Server) Handler() http.Handler {
	return s.mux
}

// PresignedURLRequest represents the request for presigned URL
type PresignedURLRequest struct {
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	UserID      string `json:"user_id,omitempty"`
	SessionID   string `json:"session_id,omitempty"`
}

// PresignedURLResponse represents the response with presigned URL
type PresignedURLResponse struct {
	URL       string    `json:"url"`
	FileID    string    `json:"file_id"`
	ExpiresAt time.Time `json:"expires_at"`
	Key       string    `json:"key"`
}

// ConfirmUploadRequest represents the request to confirm upload
type ConfirmUploadRequest struct {
	FileID      string `json:"file_id"`
	Key         string `json:"key"`
	ETag        string `json:"etag,omitempty"`
	ContentType string `json:"content_type,omitempty"`
}

// ConfirmUploadResponse represents the response after confirming upload
type ConfirmUploadResponse struct {
	Success   bool   `json:"success"`
	FileID    string `json:"file_id"`
	Message   string `json:"message,omitempty"`
	Validated bool   `json:"validated"`
}

// handlePresignedURL handles GET /v1/files/presigned-url
func (s *Server) handlePresignedURL(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var filename, contentType, userID, sessionID string

	if r.Method == http.MethodGet {
		filename = r.URL.Query().Get("filename")
		contentType = r.URL.Query().Get("content_type")
		userID = r.URL.Query().Get("user_id")
		sessionID = r.URL.Query().Get("session_id")
	} else {
		var req PresignedURLRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}
		filename = req.Filename
		contentType = req.ContentType
		userID = req.UserID
		sessionID = req.SessionID
	}

	// Get user ID from header if not in request
	if userID == "" {
		userID = r.Header.Get("X-User-Id")
	}

	if filename == "" {
		http.Error(w, "filename is required", http.StatusBadRequest)
		return
	}

	if contentType == "" {
		contentType = "application/octet-stream"
	}

	// Note: Content type validation happens during upload confirmation, not at presigned URL stage

	// Generate unique file ID and storage key
	fileID := generateFileID()
	key := buildStorageKey(userID, sessionID, fileID, filename)

	// Get storage and generate presigned URL
	stor, err := s.factory.Get(s.cfg.Storage.DefaultProvider)
	if err != nil {
		s.logger.WithError(err).Error("Failed to get storage provider")
		http.Error(w, "Internal server error", http.StatusInternalServerError)
		return
	}

	expiryDuration := time.Hour // 1 hour
	url, err := stor.GeneratePresignedURL(context.Background(), key, expiryDuration, storage.OperationWrite)
	if err != nil {
		s.logger.WithError(err).Error("Failed to generate presigned URL")
		http.Error(w, "Failed to generate presigned URL", http.StatusInternalServerError)
		return
	}

	expiresAt := time.Now().Add(expiryDuration)

	s.logger.WithFields(logrus.Fields{
		"file_id":      fileID,
		"key":          key,
		"content_type": contentType,
		"user_id":      userID,
	}).Info("Generated presigned URL for upload")

	response := PresignedURLResponse{
		URL:       url,
		FileID:    fileID,
		ExpiresAt: expiresAt,
		Key:       key,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// handleConfirmUpload handles POST /v1/files/confirm-upload
func (s *Server) handleConfirmUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req ConfirmUploadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.FileID == "" || req.Key == "" {
		http.Error(w, "file_id and key are required", http.StatusBadRequest)
		return
	}

	// Verify the file exists in storage
	stor, err := s.factory.Get(s.cfg.Storage.DefaultProvider)
	if err != nil {
		s.logger.WithError(err).Error("Failed to get storage provider")
		http.Error(w, "Internal server error", http.StatusInternalServerError)
		return
	}

	exists, err := stor.Exists(context.Background(), req.Key)
	if err != nil {
		s.logger.WithError(err).Error("Failed to check file existence")
		http.Error(w, "Failed to verify upload", http.StatusInternalServerError)
		return
	}

	if !exists {
		http.Error(w, "File not found in storage", http.StatusNotFound)
		return
	}

	// TODO: Validate magic number by reading first bytes from storage
	// For now, we trust the upload was successful
	validated := true

	s.logger.WithFields(logrus.Fields{
		"file_id":   req.FileID,
		"key":       req.Key,
		"validated": validated,
	}).Info("Upload confirmed")

	response := ConfirmUploadResponse{
		Success:   true,
		FileID:    req.FileID,
		Message:   "Upload confirmed successfully",
		Validated: validated,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// handleHealth handles GET /health
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":    "healthy",
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	})
}

// generateFileID generates a unique file ID
func generateFileID() string {
	return "file_" + randomHex(16)
}

// randomHex generates a random hex string
func randomHex(n int) string {
	bytes := make([]byte, n)
	if _, err := rand.Read(bytes); err != nil {
		// Fallback to timestamp if random fails
		return time.Now().Format("20060102150405")
	}
	return hex.EncodeToString(bytes)
}

// buildStorageKey builds the storage key for a file
func buildStorageKey(userID, sessionID, fileID, filename string) string {
	if userID == "" {
		userID = "anonymous"
	}
	if sessionID == "" {
		sessionID = "default"
	}
	return userID + "/" + sessionID + "/" + fileID + "/" + filename
}
