package v1

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

// ExportsDeps contains HTTP-only dependencies for the APKG export resource.
// River scheduling and Anki construction are owned by the export use case.
type ExportsDeps struct {
	WriteJSON func(w http.ResponseWriter, status int, v any)
	UserID    func(r *http.Request) string
	ReadModel usecase.ReadModel
	Service   usecase.APKGExport
}

type apkgExportRequest struct {
	SessionID  string `json:"session_id"`
	TemplateID string `json:"template_id,omitempty"`
	DeckName   string `json:"deck_name,omitempty"`
}

func NewApkgExportsHandler(deps ExportsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleCreateApkgExport(w, r, deps)
	}
}

func NewApkgExportDetailRouter(deps ExportsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.ReadModel == nil || !deps.ReadModel.Ready() {
			http.Error(w, "storage unavailable", http.StatusServiceUnavailable)
			return
		}
		trimmed := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/exports/apkg/"), "/")
		parts := strings.Split(trimmed, "/")
		if len(parts) == 0 || strings.TrimSpace(parts[0]) == "" {
			http.NotFound(w, r)
			return
		}
		exportID := strings.TrimSpace(parts[0])
		switch {
		case len(parts) == 1 && r.Method == http.MethodGet:
			handleGetApkgExport(w, r, deps, exportID)
		case len(parts) == 2 && parts[1] == "download" && r.Method == http.MethodGet:
			handleDownloadApkgExport(w, r, deps, exportID)
		case len(parts) == 1 || (len(parts) == 2 && parts[1] == "download"):
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		default:
			http.NotFound(w, r)
		}
	}
}

func handleCreateApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps) {
	var request apkgExportRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	request.SessionID = strings.TrimSpace(request.SessionID)
	request.TemplateID = strings.TrimSpace(request.TemplateID)
	request.DeckName = strings.TrimSpace(request.DeckName)
	if request.SessionID == "" {
		http.Error(w, "session_id is required", http.StatusBadRequest)
		return
	}
	if deps.Service == nil {
		http.Error(w, "export service unavailable", http.StatusServiceUnavailable)
		return
	}
	result, err := deps.Service.CreateAPKGExport(r.Context(), usecase.CreateAPKGExportCommand{
		SessionID: request.SessionID, UserID: deps.UserID(r), TemplateID: request.TemplateID, DeckName: request.DeckName,
	})
	if err != nil {
		http.Error(w, "failed to create export task", http.StatusInternalServerError)
		return
	}
	deps.WriteJSON(w, http.StatusAccepted, exportResultResponse(result))
}

func handleGetApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps, exportID string) {
	sessionID := strings.TrimSpace(r.URL.Query().Get("session_id"))
	if sessionID == "" {
		http.Error(w, "session_id query is required", http.StatusBadRequest)
		return
	}
	if deps.Service == nil {
		http.Error(w, "export service unavailable", http.StatusServiceUnavailable)
		return
	}
	result, err := deps.Service.GetAPKGExport(r.Context(), exportID, sessionID, deps.UserID(r))
	if err != nil {
		http.Error(w, "export task not found", http.StatusNotFound)
		return
	}
	deps.WriteJSON(w, http.StatusOK, exportResultResponse(result))
}

func handleDownloadApkgExport(w http.ResponseWriter, r *http.Request, deps ExportsDeps, exportID string) {
	sessionID := strings.TrimSpace(r.URL.Query().Get("session_id"))
	if sessionID == "" {
		http.Error(w, "session_id query is required", http.StatusBadRequest)
		return
	}
	if deps.Service == nil {
		http.Error(w, "export service unavailable", http.StatusServiceUnavailable)
		return
	}
	download, err := deps.Service.DownloadAPKGExport(r.Context(), exportID, sessionID, deps.UserID(r))
	if err != nil {
		http.Error(w, "export task not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s\"", download.FileName))
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(download.Content)
}

func exportResultResponse(result usecase.APKGExportResult) map[string]any {
	response := map[string]any{
		"export_id": result.ExportID, "session_id": result.SessionID, "template_id": result.TemplateID,
		"status": result.Status, "deck_name": result.DeckName, "package_name": result.PackageName,
		"confirmed_count": result.ConfirmedCount, "file_name": result.FileName, "file_size": result.FileSize,
		"download_path": result.DownloadPath, "error": result.Error,
	}
	if !result.CreatedAt.IsZero() {
		response["created_at"] = result.CreatedAt.UTC().Format(time.RFC3339)
	}
	if !result.UpdatedAt.IsZero() {
		response["updated_at"] = result.UpdatedAt.UTC().Format(time.RFC3339)
	}
	if result.CompletedAt != nil {
		response["completed_at"] = result.CompletedAt.UTC().Format(time.RFC3339)
	}
	return response
}
