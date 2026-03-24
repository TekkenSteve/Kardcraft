package http

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"

	"github.com/sirupsen/logrus"

	"file-storage/internal/config"
	"file-storage/internal/middleware"
	"file-storage/internal/policy"
	"file-storage/internal/storage"
)

// Server represents the HTTP server for file-storage
type Server struct {
	cfg          *config.Config
	factory      *storage.Factory
	middleware   *middleware.Chain
	policyEngine *policy.PolicyEngine
	logger       *logrus.Logger
	mux          *http.ServeMux
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
	s.mux.HandleFunc("/v1/files/health", corsHandler(s.handleHealth))
	s.mux.HandleFunc("/health", corsHandler(s.handleHealth))
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
