// Package template implements application operations for template rendering
// and validation. It deliberately owns no HTTP endpoint knowledge.
package template

import (
	"context"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

type Service struct {
	readModel usecase.ReadModel
	runtime   usecase.TemplateRuntime
}

func New(readModel usecase.ReadModel, runtime usecase.TemplateRuntime) (*Service, error) {
	if readModel == nil || runtime == nil {
		return nil, fmt.Errorf("template read model and runtime are required")
	}
	return &Service{readModel: readModel, runtime: runtime}, nil
}

func (s *Service) ListTemplates(ctx context.Context, userID string, limit, offset int) (usecase.TemplateListResult, error) {
	rows, total, err := s.readModel.ListAccessibleTemplates(ctx, strings.TrimSpace(userID), limit, offset)
	if err != nil {
		return usecase.TemplateListResult{}, err
	}
	result := usecase.TemplateListResult{Templates: make([]usecase.TemplateSummary, 0, len(rows)), TotalCount: total}
	if resolved, err := s.readModel.GetResolvedDefaultTemplate(ctx, userID); err == nil && resolved != nil {
		result.UserDefaultTemplateID = strings.TrimSpace(resolved.DefaultTemplateID)
		result.UserDefaultTemplateVersion = resolved.DefaultTemplateVersion
	}
	for _, row := range rows {
		summary := templateSummary(row)
		summary.IsDefault = result.UserDefaultTemplateID != "" && summary.TemplateID == result.UserDefaultTemplateID
		result.Templates = append(result.Templates, summary)
	}
	return result, nil
}

func (s *Service) GetTemplate(ctx context.Context, userID, templateID string) (usecase.TemplateDetailResult, error) {
	row, err := s.readModel.GetAccessibleTemplate(ctx, strings.TrimSpace(userID), strings.TrimSpace(templateID))
	if err != nil || row == nil {
		return usecase.TemplateDetailResult{}, err
	}
	result := templateDetail(*row)
	if resolved, err := s.readModel.GetResolvedDefaultTemplate(ctx, userID); err == nil && resolved != nil {
		result.IsDefault = result.TemplateID == strings.TrimSpace(resolved.DefaultTemplateID)
	}
	return result, nil
}

func (s *Service) ImportTemplate(ctx context.Context, userID string, command usecase.TemplateImportCommand) (usecase.TemplateImportResult, error) {
	command = normalizeImport(command)
	if command.Name == "" || command.FrontHTML == "" || command.BackHTML == "" || command.CSS == "" {
		return usecase.TemplateImportResult{}, fmt.Errorf("name, front_html, back_html, and css are required")
	}
	row, err := s.readModel.ImportUserTemplate(ctx, strings.TrimSpace(userID), usecase.TemplateImport{
		SourceTemplateID: command.SourceTemplateID, Name: command.Name, Description: command.Description, Tags: command.Tags,
		Metadata: command.Metadata, FrontHTML: command.FrontHTML, BackHTML: command.BackHTML, CSS: command.CSS, JS: command.JS,
		MappingSpec: command.MappingSpec, AssetsManifest: command.AssetsManifest, Compatibility: command.Compatibility,
		Changelog: command.Changelog, Published: command.Published,
	})
	if err != nil {
		return usecase.TemplateImportResult{}, err
	}
	return usecase.TemplateImportResult{TemplateID: row.TemplateID, Version: row.LatestVersion}, nil
}

func (s *Service) GetDefaultTemplate(ctx context.Context, userID string) (usecase.TemplateDefaultResult, error) {
	row, err := s.readModel.GetResolvedDefaultTemplate(ctx, strings.TrimSpace(userID))
	if err != nil || row == nil {
		return usecase.TemplateDefaultResult{}, err
	}
	return usecase.TemplateDefaultResult{UserID: strings.TrimSpace(userID), TemplateID: row.DefaultTemplateID, Version: row.DefaultTemplateVersion}, nil
}

func (s *Service) SetDefaultTemplate(ctx context.Context, userID string, command usecase.SetDefaultTemplateCommand) (usecase.TemplateDefaultResult, error) {
	command.TemplateID = strings.TrimSpace(command.TemplateID)
	if command.TemplateID == "" {
		return usecase.TemplateDefaultResult{}, fmt.Errorf("default template id is required")
	}
	if command.Version <= 0 {
		command.Version = 1
	}
	if err := s.readModel.UpsertUserTemplatePreference(ctx, strings.TrimSpace(userID), command.TemplateID, command.Version); err != nil {
		return usecase.TemplateDefaultResult{}, err
	}
	return usecase.TemplateDefaultResult{UserID: strings.TrimSpace(userID), TemplateID: command.TemplateID, Version: command.Version}, nil
}

func (s *Service) ExportTemplate(ctx context.Context, userID, templateID string, exportedAt time.Time) (usecase.TemplateExportResult, error) {
	template, err := s.GetTemplate(ctx, userID, templateID)
	if err != nil {
		return usecase.TemplateExportResult{}, err
	}
	return usecase.TemplateExportResult{Template: template, ExportedAt: exportedAt.UTC()}, nil
}

func templateSummary(row usecase.TemplateCatalogRow) usecase.TemplateSummary {
	return usecase.TemplateSummary{TemplateID: row.TemplateID, Name: row.Name, Description: row.Description, Scope: row.Scope,
		OwnerUserID: row.OwnerUserID, Status: row.Status, IsDefault: row.IsDefault, LatestVersion: row.LatestVersion,
		VersionPublished: row.VersionPublished, CreatedAt: row.CreatedAt, UpdatedAt: row.UpdatedAt, Tags: row.Tags}
}

func templateDetail(row usecase.TemplateCatalogRow) usecase.TemplateDetailResult {
	return usecase.TemplateDetailResult{TemplateSummary: templateSummary(row), Tags: row.Tags, Metadata: row.Metadata,
		FrontHTML: row.FrontHTML, BackHTML: row.BackHTML, CSS: row.CSS, JS: row.JS, MappingSpec: row.MappingSpec,
		AssetsManifest: row.AssetsManifest, Compatibility: row.Compatibility, Changelog: row.Changelog}
}

func normalizeImport(command usecase.TemplateImportCommand) usecase.TemplateImportCommand {
	command.SourceTemplateID = strings.TrimSpace(command.SourceTemplateID)
	command.Name = strings.TrimSpace(command.Name)
	command.Description = strings.TrimSpace(command.Description)
	command.FrontHTML = strings.TrimSpace(command.FrontHTML)
	command.BackHTML = strings.TrimSpace(command.BackHTML)
	command.CSS = strings.TrimSpace(command.CSS)
	command.JS = strings.TrimSpace(command.JS)
	command.Changelog = strings.TrimSpace(command.Changelog)
	return command
}

func (s *Service) ExecuteTemplateOperation(ctx context.Context, command usecase.TemplateOperationCommand) (usecase.TemplateOperationResult, error) {
	if s == nil || s.runtime == nil {
		return usecase.TemplateOperationResult{}, fmt.Errorf("template runtime is required")
	}
	if !supportedOperation(command.Operation) {
		return usecase.TemplateOperationResult{}, fmt.Errorf("unsupported template operation: %s", command.Operation)
	}
	if command.Payload == nil {
		command.Payload = map[string]any{}
	}
	return s.runtime.ExecuteTemplateRuntime(ctx, command.Operation, command.Payload)
}

func (s *Service) PrepareTemplateOperation(ctx context.Context, userID string, command usecase.TemplateOperationCommand) (usecase.TemplateOperationCommand, error) {
	if !supportedOperation(command.Operation) {
		return usecase.TemplateOperationCommand{}, fmt.Errorf("unsupported template operation: %s", command.Operation)
	}
	payload := copyPayload(command.Payload)
	templateID := stringField(payload, "template_id")
	if templateID != "" {
		row, err := s.readModel.GetAccessibleTemplate(ctx, strings.TrimSpace(userID), templateID)
		if err != nil {
			return usecase.TemplateOperationCommand{}, fmt.Errorf("load accessible template: %w", err)
		}
		if row == nil {
			return usecase.TemplateOperationCommand{}, fmt.Errorf("load accessible template: template not found")
		}
		if stringField(payload, "front_html") == "" {
			payload["front_html"] = row.FrontHTML
		}
		if stringField(payload, "back_html") == "" {
			payload["back_html"] = row.BackHTML
		}
		if stringField(payload, "css") == "" {
			payload["css"] = row.CSS
		}
		if command.Operation == usecase.TemplateOperationPreview || command.Operation == usecase.TemplateOperationValidate {
			if stringField(payload, "js") == "" {
				payload["js"] = row.JS
			}
			payload["version"] = row.LatestVersion
		}
		if command.Operation == usecase.TemplateOperationPreview && len(row.MappingSpec) > 0 {
			payload["mapping_spec"] = row.MappingSpec
		}
	}
	if command.Operation != usecase.TemplateOperationBuildAPKG && (stringField(payload, "front_html") == "" || stringField(payload, "back_html") == "") {
		return usecase.TemplateOperationCommand{}, fmt.Errorf("front_html and back_html are required")
	}
	return usecase.TemplateOperationCommand{Operation: command.Operation, Payload: payload}, nil
}

func supportedOperation(operation usecase.TemplateOperation) bool {
	switch operation {
	case usecase.TemplateOperationPreview, usecase.TemplateOperationValidate, usecase.TemplateOperationRequiredFields, usecase.TemplateOperationPrecheck, usecase.TemplateOperationBuildAPKG:
		return true
	default:
		return false
	}
}

func copyPayload(payload map[string]any) map[string]any {
	copy := make(map[string]any, len(payload))
	for key, value := range payload {
		copy[key] = value
	}
	return copy
}

func stringField(payload map[string]any, key string) string {
	value, _ := payload[key].(string)
	return strings.TrimSpace(value)
}
