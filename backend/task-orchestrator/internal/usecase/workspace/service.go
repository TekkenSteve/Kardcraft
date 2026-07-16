// Package workspace owns Kardcraft's workspace projection and card mutations.
package workspace

import (
	"context"
	"fmt"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

type Service struct {
	readModel usecase.ReadModel
	now       func() time.Time
}

const (
	idleThreshold = 6 * time.Hour
	ttlThreshold  = 72 * time.Hour
)

func New(readModel usecase.ReadModel) (*Service, error) {
	if readModel == nil {
		return nil, fmt.Errorf("workspace read model is required")
	}
	return &Service{readModel: readModel, now: time.Now}, nil
}

func (s *Service) GetWorkspace(ctx context.Context, sessionID, userID string) (usecase.WorkspaceSnapshot, error) {
	if _, err := s.readModel.GetSession(ctx, strings.TrimSpace(sessionID), strings.TrimSpace(userID)); err != nil {
		return usecase.WorkspaceSnapshot{}, fmt.Errorf("get workspace session: %w", err)
	}
	payload, err := s.readModel.LoadWorkspace(ctx, strings.TrimSpace(sessionID))
	if err != nil {
		return usecase.WorkspaceSnapshot{}, fmt.Errorf("load workspace: %w", err)
	}
	return usecase.WorkspaceSnapshot{SessionID: strings.TrimSpace(sessionID), Payload: normalizeWorkspace(payload, sessionID)}, nil
}

func (s *Service) BulkUpdateCards(ctx context.Context, command usecase.BulkCardUpdateCommand) (usecase.BulkCardUpdateResult, error) {
	command = normalizeBulkCommand(command)
	if command.SessionID == "" || command.UserID == "" || len(command.CardIDs) == 0 {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("session, user, and card IDs are required")
	}
	if command.Action != "update_status" && command.Action != "update_question_type" {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("unsupported card bulk action")
	}
	if command.Action == "update_status" && !validCardStatus(command.Status) {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("invalid card status")
	}
	if command.Action == "update_question_type" && command.QuestionType == "" {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("question type is required")
	}
	if _, err := s.readModel.GetSession(ctx, command.SessionID, command.UserID); err != nil {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("get workspace session: %w", err)
	}
	raw, err := s.readModel.LoadWorkspace(ctx, command.SessionID)
	if err != nil {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("load workspace: %w", err)
	}
	workspace := normalizeWorkspace(raw, command.SessionID)
	idSet := make(map[string]struct{}, len(command.CardIDs))
	for _, cardID := range command.CardIDs {
		idSet[cardID] = struct{}{}
	}
	now := s.now().UTC().Format(time.RFC3339)
	updated := 0
	for _, card := range workspaceCards(workspace) {
		cardID, _ := card["card_id"].(string)
		if _, exists := idSet[cardID]; !exists {
			continue
		}
		content := mapValue(card, "content")
		editState := mapValue(card, "edit_state")
		meta := mapValue(card, "meta")
		switch command.Action {
		case "update_status":
			editState["status"] = command.Status
		case "update_question_type":
			content["model"] = command.QuestionType
		}
		meta["modified_at"] = now
		updated++
	}
	workspace["version"] = workspaceVersion(workspace) + 1
	workspace["status"] = "active"
	workspace["updated_at"] = now
	if err := s.readModel.SaveWorkspace(ctx, command.SessionID, workspace); err != nil {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("save workspace: %w", err)
	}
	if err := s.readModel.MarkSessionActive(ctx, command.SessionID, command.UserID); err != nil {
		return usecase.BulkCardUpdateResult{}, fmt.Errorf("mark session active: %w", err)
	}
	return usecase.BulkCardUpdateResult{Updated: updated}, nil
}

func (s *Service) DescribeWorkspace(ctx context.Context, sessionID string, now time.Time) (usecase.WorkspaceContext, error) {
	raw, err := s.readModel.LoadWorkspace(ctx, strings.TrimSpace(sessionID))
	if err != nil || raw == nil {
		return usecase.WorkspaceContext{}, err
	}
	workspace := normalizeWorkspace(raw, sessionID)
	result := usecase.WorkspaceContext{Available: true, Status: stringValue(workspace["status"]), Version: int64(workspaceVersion(workspace))}
	result.LifecycleState, result.UpdatedAt, result.AgeHours = lifecycleState(result.Status, stringValue(workspace["updated_at"]), now)
	cards := workspaceCards(workspace)
	result.CardCount = len(cards)
	result.Cards = make([]usecase.WorkspaceCardSummary, 0, min(5, len(cards)))
	for _, card := range cards {
		result.Cards = append(result.Cards, usecase.WorkspaceCardSummary{ID: stringValue(card["id"]), Title: stringValue(card["title"]), Type: stringValue(card["type"])})
		if len(result.Cards) == 5 {
			break
		}
	}
	return result, nil
}

func normalizeWorkspace(raw map[string]any, sessionID string) map[string]any {
	result := map[string]any{"session_id": strings.TrimSpace(sessionID), "version": 0, "status": "not_started", "cards": []map[string]any{}, "card_count": 0, "projection_status": "empty"}
	if raw == nil {
		return result
	}
	for _, key := range []string{"session_id", "version", "status", "template_id", "selected_question_type", "supported_question_types", "updated_at"} {
		if value, exists := raw[key]; exists {
			result[key] = value
		}
	}
	cards := workspaceCards(raw)
	result["cards"] = cards
	result["card_count"] = len(cards)
	if len(cards) > 0 {
		result["projection_status"] = "hydrated"
	}
	return result
}

func workspaceCards(workspace map[string]any) []map[string]any {
	if cards, ok := workspace["cards"].([]map[string]any); ok {
		return cards
	}
	items, _ := workspace["cards"].([]any)
	cards := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if card, ok := item.(map[string]any); ok {
			cards = append(cards, card)
		}
	}
	return cards
}

func mapValue(container map[string]any, key string) map[string]any {
	if value, ok := container[key].(map[string]any); ok && value != nil {
		return value
	}
	value := map[string]any{}
	container[key] = value
	return value
}

func workspaceVersion(workspace map[string]any) int {
	switch value := workspace["version"].(type) {
	case int:
		return value
	case int64:
		return int(value)
	case float64:
		return int(value)
	default:
		return 0
	}
}

func normalizeBulkCommand(command usecase.BulkCardUpdateCommand) usecase.BulkCardUpdateCommand {
	command.SessionID = strings.TrimSpace(command.SessionID)
	command.UserID = strings.TrimSpace(command.UserID)
	command.Action = strings.TrimSpace(command.Action)
	command.Status = strings.TrimSpace(command.Status)
	command.QuestionType = strings.TrimSpace(command.QuestionType)
	return command
}

func validCardStatus(status string) bool {
	switch status {
	case "draft", "ai_editing", "user_editing", "confirmed":
		return true
	default:
		return false
	}
}

func lifecycleState(status, updatedAt string, now time.Time) (string, string, float64) {
	status = strings.ToLower(strings.TrimSpace(status))
	if status == "recycled" {
		return "recycled", updatedAt, 0
	}
	if updatedAt == "" {
		if status == "active" {
			return "active", "", 0
		}
		return "idle", "", 0
	}
	parsed, err := time.Parse(time.RFC3339, updatedAt)
	if err != nil {
		return "idle", updatedAt, 0
	}
	age := now.UTC().Sub(parsed.UTC())
	if age < 0 {
		age = 0
	}
	ageHours := float64(int(age.Hours()*100)) / 100
	switch {
	case age >= ttlThreshold:
		return "ttl_expired", parsed.UTC().Format(time.RFC3339), ageHours
	case age >= idleThreshold:
		return "idle", parsed.UTC().Format(time.RFC3339), ageHours
	default:
		return "active", parsed.UTC().Format(time.RFC3339), ageHours
	}
}

func stringValue(value any) string {
	text, _ := value.(string)
	return strings.TrimSpace(text)
}
