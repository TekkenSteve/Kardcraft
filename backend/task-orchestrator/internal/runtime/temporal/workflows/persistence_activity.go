package workflows

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"task-orchestrator/internal/repo/persistence"
)

type PersistTaskOutcomeInput struct {
	TaskID       string         `json:"task_id"`
	Status       string         `json:"status"`
	Result       map[string]any `json:"result,omitempty"`
	Error        string         `json:"error,omitempty"`
	CompletedAt  time.Time      `json:"completed_at"`
	WorkflowID   string         `json:"workflow_id,omitempty"`
	TerminalNote string         `json:"terminal_note,omitempty"`
}

type taskOutcomeStore interface {
	UpdateTaskFinalState(ctx context.Context, taskID string, status string, result any, errMsg string, completedAt time.Time) error
	GetTaskSession(ctx context.Context, taskID string) (string, error)
	InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error
	LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error)
	SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error
}

var persistenceStore taskOutcomeStore

func ConfigureTaskPersistenceStore(store *persistence.SessionStore) {
	persistenceStore = store
}

func PersistTaskOutcomeActivity(ctx context.Context, in PersistTaskOutcomeInput) error {
	if persistenceStore == nil {
		return fmt.Errorf("session store not configured")
	}
	taskID := strings.TrimSpace(in.TaskID)
	if taskID == "" {
		return fmt.Errorf("task_id is required")
	}
	status := strings.TrimSpace(strings.ToLower(in.Status))
	if status == "" {
		status = "completed"
	}
	outcome, err := DecodeTaskOutcome(in.Result)
	if err != nil {
		if status == "completed" {
			log.Printf("metric=outcome_decode_failure task_id=%s workflow_id=%s status=%s err=%v", taskID, in.WorkflowID, status, err)
			return fmt.Errorf("decode task outcome: %w", err)
		}
		outcome = TaskOutcome{
			SchemaVersion: TaskOutcomeSchema,
			TaskID:        taskID,
			WorkflowID:    strings.TrimSpace(in.WorkflowID),
			Status:        status,
			Message:       strings.TrimSpace(in.Error),
		}
	} else {
		log.Printf("metric=outcome_decode_success task_id=%s workflow_id=%s schema=%s", taskID, in.WorkflowID, outcome.SchemaVersion)
	}
	if outcome.Status == "" {
		outcome.Status = status
	}
	if outcome.TaskID == "" {
		outcome.TaskID = taskID
	}
	if outcome.WorkflowID == "" {
		outcome.WorkflowID = strings.TrimSpace(in.WorkflowID)
		if outcome.WorkflowID == "" {
			outcome.WorkflowID = taskID
		}
	}
	if status != "" && status != outcome.Status {
		outcome.Status = status
	}

	if err := persistenceStore.UpdateTaskFinalState(ctx, taskID, outcome.Status, outcome.ToMap(), in.Error, in.CompletedAt); err != nil {
		log.Printf("metric=outcome_persist_critical_failure task_id=%s workflow_id=%s err=%v", taskID, outcome.WorkflowID, err)
		return err
	}

	sessionID, _ := persistenceStore.GetTaskSession(ctx, taskID)
	if strings.TrimSpace(sessionID) == "" {
		sessionID = strings.TrimSpace(outcome.SessionID)
	}
	if strings.TrimSpace(sessionID) == "" {
		return nil
	}
	workflowID := strings.TrimSpace(outcome.WorkflowID)

	eventType := "WORKFLOW_COMPLETED"
	if outcome.Status == "failed" {
		eventType = "WORKFLOW_FAILED"
	} else if outcome.Status == "cancelled" {
		eventType = "WORKFLOW_CANCELLED"
	}
	msg := strings.TrimSpace(in.TerminalNote)
	if msg == "" {
		msg = strings.TrimSpace(outcome.Message)
	}
	if msg == "" {
		switch eventType {
		case "WORKFLOW_COMPLETED":
			msg = "Workflow completed"
		case "WORKFLOW_FAILED":
			msg = firstNonEmpty(strings.TrimSpace(in.Error), "Workflow failed")
		default:
			msg = "Workflow cancelled"
		}
	}
	if err := persistenceStore.InsertEvent(
		ctx,
		sessionID,
		taskID,
		workflowID,
		eventType,
		msg,
		"",
		"terminal:"+taskID+":"+outcome.Status,
		time.Now().UTC(),
	); err != nil {
		log.Printf("metric=projection_failure type=terminal_event task_id=%s workflow_id=%s err=%v", taskID, workflowID, err)
	}

	if outcome.Status == "completed" {
		cards := buildWorkspaceCards(outcome.FinalCards, outcome.UserID)
		if len(cards) > 0 {
			nextVersion := 1
			if currentWorkspace, err := persistenceStore.LoadWorkspace(ctx, sessionID); err == nil {
				nextVersion = workspaceVersion(currentWorkspace) + 1
			}
			now := time.Now().UTC()
			workspace := map[string]any{
				"session_id": sessionID,
				"status":     "active",
				"card_count": len(cards),
				"cards":      cards,
				"updated_at": now.Format(time.RFC3339),
				"version":    nextVersion,
			}
			if len(outcome.Metadata) > 0 {
				if templateID := strings.TrimSpace(asString(outcome.Metadata["template_id"])); templateID != "" {
					workspace["template_id"] = templateID
				}
				if supported := normalizeStringSlice(asAnySlice(outcome.Metadata["supported_question_types"])); len(supported) > 0 {
					workspace["supported_question_types"] = supported
				}
				if selected := strings.TrimSpace(asString(outcome.Metadata["selected_question_type"])); selected != "" {
					workspace["selected_question_type"] = selected
				}
			}
			if err := persistenceStore.SaveWorkspace(ctx, sessionID, workspace); err != nil {
				log.Printf("metric=projection_failure type=workspace task_id=%s workflow_id=%s err=%v", taskID, workflowID, err)
			} else {
				workspacePayload, _ := json.Marshal(map[string]any{
					"session_id": sessionID,
					"version":    nextVersion,
					"card_count": len(cards),
					"status":     "active",
				})
				if err := persistenceStore.InsertEvent(
					ctx,
					sessionID,
					taskID,
					workflowID,
					"WORKSPACE_UPDATED",
					"Workspace updated",
					string(workspacePayload),
					fmt.Sprintf("workspace:%s:%d", taskID, nextVersion),
					now,
				); err != nil {
					log.Printf("metric=projection_failure type=workspace_event task_id=%s workflow_id=%s err=%v", taskID, workflowID, err)
				}
			}
		}
	}

	return nil
}

func workspaceVersion(workspace map[string]any) int {
	if workspace == nil {
		return 0
	}
	switch v := workspace["version"].(type) {
	case int:
		return v
	case int32:
		return int(v)
	case int64:
		return int(v)
	case float64:
		return int(v)
	default:
		return 0
	}
}

func buildWorkspaceCards(cards []TaskOutcomeCard, userID string) []map[string]any {
	if len(cards) == 0 {
		return []map[string]any{}
	}
	now := time.Now().UTC().Format(time.RFC3339)
	out := make([]map[string]any, 0, len(cards))
	for _, card := range cards {
		cardID := strings.TrimSpace(card.ID)
		if cardID == "" {
			cardID = fmt.Sprintf("card_%d", time.Now().UTC().UnixNano())
		}
		front := strings.TrimSpace(card.Front)
		back := strings.TrimSpace(card.Back)
		model := strings.TrimSpace(card.Model)
		if model == "" {
			model = "mcq"
		}
		suggestedQuestionType := strings.TrimSpace(card.SuggestedQuestionType)
		if suggestedQuestionType == "" {
			suggestedQuestionType = model
		}
		tags := card.Tags

		out = append(out, map[string]any{
			"id":      cardID,
			"user_id": userID,
			"card_id": cardID,
			"suggested_question_type": suggestedQuestionType,
			"content": map[string]any{
				"version": 1,
				"model":   model,
				"data": map[string]any{
					"front":    front,
					"back":     back,
					"tags":     tags,
					"concepts": []string{},
				},
				"media": []any{},
			},
			"edit_state": map[string]any{
				"status": "draft",
			},
			"concepts": []string{},
			"meta": map[string]any{
				"created_at":   now,
				"modified_at":  now,
				"manual_edits": 0,
			},
		})
	}
	return out
}
