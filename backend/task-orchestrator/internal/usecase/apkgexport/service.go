// Package apkgexport implements Kardcraft's APKG export business workflow.
package apkgexport

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
)

type Service struct {
	readModel usecase.ReadModel
	exports   repo.APKGExportStore
}

func New(readModel usecase.ReadModel, exports repo.APKGExportStore) (*Service, error) {
	if readModel == nil || exports == nil {
		return nil, fmt.Errorf("read model and APKG export store are required")
	}
	return &Service{readModel: readModel, exports: exports}, nil
}

func (s *Service) CreateAPKGExport(ctx context.Context, command usecase.CreateAPKGExportCommand) (usecase.APKGExportResult, error) {
	command = normalizeCommand(command)
	if command.SessionID == "" || command.UserID == "" {
		return usecase.APKGExportResult{}, fmt.Errorf("session and user are required")
	}
	if _, err := s.readModel.GetSession(ctx, command.SessionID, command.UserID); err != nil {
		return usecase.APKGExportResult{}, fmt.Errorf("get export session: %w", err)
	}
	export := repo.APKGExport{
		ExportID:   "apkg_" + uuid.NewString(),
		SessionID:  command.SessionID,
		UserID:     command.UserID,
		TemplateID: command.TemplateID,
		DeckName:   command.DeckName,
		Status:     "queued",
	}
	if err := s.exports.CreateAndEnqueueAPKGExport(ctx, export); err != nil {
		return usecase.APKGExportResult{}, err
	}
	now := time.Now().UTC()
	export.CreatedAt = now
	export.UpdatedAt = now
	return exportResult(export), nil
}

func (s *Service) GetAPKGExport(ctx context.Context, exportID, sessionID, userID string) (usecase.APKGExportResult, error) {
	export, found, err := s.exports.GetAPKGExport(ctx, exportID, sessionID, userID)
	if err != nil {
		return usecase.APKGExportResult{}, err
	}
	if !found {
		return usecase.APKGExportResult{}, fmt.Errorf("APKG export not found")
	}
	return exportResult(export), nil
}

func (s *Service) DownloadAPKGExport(ctx context.Context, exportID, sessionID, userID string) (usecase.APKGExportDownload, error) {
	export, found, err := s.exports.GetAPKGExport(ctx, exportID, sessionID, userID)
	if err != nil {
		return usecase.APKGExportDownload{}, err
	}
	if !found {
		return usecase.APKGExportDownload{}, fmt.Errorf("APKG export not found")
	}
	if export.Status != "completed" || len(export.APKGBytes) == 0 {
		return usecase.APKGExportDownload{}, fmt.Errorf("APKG export is not ready")
	}
	fileName := strings.TrimSpace(export.FileName)
	if fileName == "" {
		fileName = "kardcraft_export.apkg"
	}
	return usecase.APKGExportDownload{FileName: fileName, Content: export.APKGBytes}, nil
}

func normalizeCommand(command usecase.CreateAPKGExportCommand) usecase.CreateAPKGExportCommand {
	command.SessionID = strings.TrimSpace(command.SessionID)
	command.UserID = strings.TrimSpace(command.UserID)
	command.TemplateID = strings.TrimSpace(command.TemplateID)
	command.DeckName = strings.TrimSpace(command.DeckName)
	return command
}

func exportResult(export repo.APKGExport) usecase.APKGExportResult {
	return usecase.APKGExportResult{
		ExportID:       export.ExportID,
		SessionID:      export.SessionID,
		TemplateID:     export.TemplateID,
		DeckName:       export.DeckName,
		PackageName:    export.PackageName,
		Status:         export.Status,
		ConfirmedCount: export.ConfirmedCount,
		FileName:       export.FileName,
		FileSize:       export.FileSize,
		DownloadPath:   "/api/v1/exports/apkg/" + export.ExportID + "/download",
		CreatedAt:      export.CreatedAt,
		UpdatedAt:      export.UpdatedAt,
		CompletedAt:    export.CompletedAt,
		Error:          export.ErrorMessage,
	}
}
