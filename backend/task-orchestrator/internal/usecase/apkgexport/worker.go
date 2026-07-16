package apkgexport

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/riverqueue/river"

	"task-orchestrator/internal/repo"
	"task-orchestrator/internal/usecase"
)

// Worker performs durable APKG export jobs. It only receives an export ID;
// user input, workspace data, and output are read and written through their
// respective application ports.
type Worker struct {
	river.WorkerDefaults[repo.APKGExportJobArgs]

	readModel usecase.ReadModel
	exports   repo.APKGExportStore
	builder   usecase.APKGBuilder
	now       func() time.Time
}

func NewWorker(readModel usecase.ReadModel, exports repo.APKGExportStore, builder usecase.APKGBuilder) (*Worker, error) {
	if readModel == nil || exports == nil || builder == nil {
		return nil, fmt.Errorf("read model, APKG export store, and builder are required")
	}
	return &Worker{readModel: readModel, exports: exports, builder: builder, now: time.Now}, nil
}

func (w *Worker) Work(ctx context.Context, job *river.Job[repo.APKGExportJobArgs]) error {
	if job == nil || strings.TrimSpace(job.Args.ExportID) == "" {
		return fmt.Errorf("APKG export job requires export_id")
	}
	export, found, err := w.exports.GetAPKGExportByID(ctx, job.Args.ExportID)
	if err != nil {
		return err
	}
	if !found || export.Status == "completed" {
		return nil
	}
	if err := w.exports.MarkAPKGExportRunning(ctx, export.ExportID); err != nil {
		return err
	}

	completed, err := w.build(ctx, export)
	if err != nil {
		if persistErr := w.recordFailure(ctx, job, export.ExportID, err); persistErr != nil {
			return fmt.Errorf("build export: %w; record failure: %v", err, persistErr)
		}
		return err
	}
	return w.exports.CompleteAPKGExport(ctx, completed)
}

func (w *Worker) recordFailure(ctx context.Context, job *river.Job[repo.APKGExportJobArgs], exportID string, buildErr error) error {
	message := exportFailureMessage(buildErr)
	if job.Attempt >= job.MaxAttempts {
		return w.exports.FailAPKGExport(ctx, exportID, message)
	}
	return w.exports.RetryAPKGExport(ctx, exportID, message)
}

func (w *Worker) build(ctx context.Context, export repo.APKGExport) (repo.APKGExport, error) {
	workspace, err := loadWorkspace(ctx, w.readModel, export.SessionID)
	if err != nil {
		return repo.APKGExport{}, err
	}
	confirmed := workspace.confirmedCards()
	if len(confirmed) == 0 {
		return repo.APKGExport{}, fmt.Errorf("no confirmed cards to export")
	}
	templateID, err := resolveTemplateID(ctx, w.readModel, export.UserID, export.TemplateID, workspace.TemplateID)
	if err != nil {
		return repo.APKGExport{}, err
	}
	template, err := w.readModel.GetAccessibleTemplate(ctx, export.UserID, templateID)
	if err != nil || template == nil {
		return repo.APKGExport{}, fmt.Errorf("load export template: %w", err)
	}
	deckName := strings.TrimSpace(export.DeckName)
	if deckName == "" {
		deckName = "Kardcraft::" + export.SessionID
	}
	packageName := fmt.Sprintf("kardcraft_%s_%d", sanitizeFileName(export.SessionID), w.now().UTC().Unix())
	fieldNames := inferFieldNames(template.FrontHTML, template.BackHTML)
	cards := make([]usecase.APKGCard, 0, len(confirmed))
	for _, card := range confirmed {
		fields, tags := card.exportFields(fieldNames, deckName)
		cards = append(cards, usecase.APKGCard{Fields: fields, Tags: tags})
	}
	result, err := w.builder.BuildAPKG(ctx, usecase.BuildAPKGRequest{
		DeckName: deckName, ModelName: template.Name, FieldNames: fieldNames,
		FrontHTML: template.FrontHTML, BackHTML: template.BackHTML, CSS: template.CSS,
		Cards: cards, PackageName: packageName,
	})
	if err != nil {
		return repo.APKGExport{}, err
	}
	if len(result.Content) == 0 {
		return repo.APKGExport{}, fmt.Errorf("Anki returned empty APKG content")
	}
	export.TemplateID = templateID
	export.DeckName = deckName
	export.PackageName = packageName
	export.ConfirmedCount = len(confirmed)
	export.FileName = firstNonEmpty(strings.TrimSpace(result.FileName), packageName+".apkg")
	export.FileSize = int64(len(result.Content))
	export.APKGBytes = result.Content
	return export, nil
}

func exportFailureMessage(err error) string {
	message := strings.TrimSpace(err.Error())
	if len(message) > 512 {
		return message[:512]
	}
	return message
}

func resolveTemplateID(ctx context.Context, readModel usecase.ReadModel, userID, explicitID, workspaceID string) (string, error) {
	if id := strings.TrimSpace(explicitID); id != "" {
		return id, nil
	}
	if id := strings.TrimSpace(workspaceID); id != "" {
		return id, nil
	}
	resolved, err := readModel.GetResolvedDefaultTemplate(ctx, userID)
	if err != nil || resolved == nil || strings.TrimSpace(resolved.DefaultTemplateID) == "" {
		return "", fmt.Errorf("no default template configured")
	}
	return strings.TrimSpace(resolved.DefaultTemplateID), nil
}

func inferFieldNames(frontHTML, backHTML string) []string {
	fields := make([]string, 0, 4)
	seen := make(map[string]struct{})
	for _, template := range []string{frontHTML, backHTML} {
		for _, token := range parseTemplateFields(template) {
			if _, exists := seen[token]; !exists {
				seen[token] = struct{}{}
				fields = append(fields, token)
			}
		}
	}
	if _, exists := seen["Front"]; !exists {
		fields = append([]string{"Front"}, fields...)
	}
	if _, exists := seen["Back"]; !exists {
		fields = append(fields, "Back")
	}
	return fields
}

func parseTemplateFields(template string) []string {
	fields := make([]string, 0)
	for remaining := template; ; {
		start := strings.Index(remaining, "{{")
		if start < 0 {
			return fields
		}
		remaining = remaining[start+2:]
		end := strings.Index(remaining, "}}")
		if end < 0 {
			return fields
		}
		token := strings.TrimSpace(remaining[:end])
		remaining = remaining[end+2:]
		token = strings.TrimLeft(token, "#/^!")
		if separator := strings.LastIndex(token, ":"); separator >= 0 {
			token = token[separator+1:]
		}
		if separator := strings.Index(token, "|"); separator >= 0 {
			token = token[:separator]
		}
		if token = strings.TrimSpace(token); token != "" {
			fields = append(fields, token)
		}
	}
}

func sanitizeFileName(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "session"
	}
	var builder strings.Builder
	for _, character := range value {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') || (character >= '0' && character <= '9') || character == '_' || character == '-' {
			builder.WriteRune(character)
		} else {
			builder.WriteByte('_')
		}
	}
	return builder.String()
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value = strings.TrimSpace(value); value != "" {
			return value
		}
	}
	return ""
}

func sortedTags(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.Join(strings.Fields(strings.TrimSpace(value)), "_")
		if value == "" {
			continue
		}
		if _, exists := seen[value]; !exists {
			seen[value] = struct{}{}
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}
