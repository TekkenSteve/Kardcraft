package workflows

import (
	"fmt"
	"strings"
)

const TaskOutcomeSchema = "task-outcome"

type TaskOutcomeCard struct {
	ID     string   `json:"id"`
	Front  string   `json:"front"`
	Back   string   `json:"back"`
	Model  string   `json:"model"`
	Status string   `json:"status,omitempty"`
	Tags   []string `json:"tags,omitempty"`
}

type TaskOutcome struct {
	SchemaVersion string            `json:"schema_version"`
	TaskID        string            `json:"task_id"`
	WorkflowID    string            `json:"workflow_id"`
	Status        string            `json:"status"`
	SessionID     string            `json:"session_id,omitempty"`
	UserID        string            `json:"user_id,omitempty"`
	Message       string            `json:"message,omitempty"`
	FinalCards    []TaskOutcomeCard `json:"final_cards,omitempty"`
	Metadata      map[string]any    `json:"metadata,omitempty"`
}

type TaskOutcomeDecodeError struct {
	Reason string
}

func (e *TaskOutcomeDecodeError) Error() string {
	if e == nil {
		return "invalid task outcome"
	}
	return "invalid task outcome: " + e.Reason
}

func BuildTaskOutcome(taskID, workflowID, status string, raw map[string]any) TaskOutcome {
	if out, err := DecodeTaskOutcome(raw); err == nil {
		if strings.TrimSpace(out.TaskID) == "" {
			out.TaskID = taskID
		}
		if strings.TrimSpace(out.WorkflowID) == "" {
			out.WorkflowID = workflowID
		}
		if strings.TrimSpace(out.Status) == "" {
			out.Status = normalizeOutcomeStatus(status)
		}
		return out
	}

	status = normalizeOutcomeStatus(status)
	if status == "" {
		status = "completed"
	}
	out := TaskOutcome{
		SchemaVersion: TaskOutcomeSchema,
		TaskID:        taskID,
		WorkflowID:    workflowID,
		Status:        status,
	}
	if len(raw) == 0 {
		return out
	}
	out.SessionID = strings.TrimSpace(asString(raw["session_id"]))
	out.UserID = strings.TrimSpace(asString(raw["user_id"]))
	out.Message = strings.TrimSpace(asString(raw["message"]))
	out.FinalCards = normalizeOutcomeCards(asAnySlice(raw["final_cards"]))
	if md, ok := raw["metadata"].(map[string]any); ok {
		out.Metadata = md
	}
	return out
}

func DecodeTaskOutcome(payload map[string]any) (TaskOutcome, error) {
	if len(payload) == 0 {
		return TaskOutcome{}, &TaskOutcomeDecodeError{Reason: "empty payload"}
	}
	schema := strings.TrimSpace(asString(payload["schema_version"]))
	if schema != "" && !strings.EqualFold(schema, TaskOutcomeSchema) {
		return TaskOutcome{}, &TaskOutcomeDecodeError{Reason: "unexpected schema_version"}
	}
	out := TaskOutcome{
		SchemaVersion: TaskOutcomeSchema,
		TaskID:        strings.TrimSpace(asString(payload["task_id"])),
		WorkflowID:    strings.TrimSpace(asString(payload["workflow_id"])),
		Status:        normalizeOutcomeStatus(asString(payload["status"])),
		SessionID:     strings.TrimSpace(asString(payload["session_id"])),
		UserID:        strings.TrimSpace(asString(payload["user_id"])),
		Message:       strings.TrimSpace(asString(payload["message"])),
	}
	if out.Status == "" {
		return TaskOutcome{}, &TaskOutcomeDecodeError{Reason: "missing status"}
	}
	out.FinalCards = normalizeOutcomeCards(asAnySlice(payload["final_cards"]))
	if md, ok := payload["metadata"].(map[string]any); ok {
		out.Metadata = md
	}
	return out, nil
}

func (o TaskOutcome) ToMap() map[string]any {
	cards := make([]map[string]any, 0, len(o.FinalCards))
	for _, card := range o.FinalCards {
		c := map[string]any{
			"id":    strings.TrimSpace(card.ID),
			"front": card.Front,
			"back":  card.Back,
			"model": firstNonEmpty(strings.TrimSpace(card.Model), "mcq"),
			"tags":  card.Tags,
		}
		if strings.TrimSpace(card.Status) != "" {
			c["status"] = strings.TrimSpace(card.Status)
		}
		cards = append(cards, c)
	}
	out := map[string]any{
		"schema_version": TaskOutcomeSchema,
		"task_id":        strings.TrimSpace(o.TaskID),
		"workflow_id":    strings.TrimSpace(o.WorkflowID),
		"status":         normalizeOutcomeStatus(o.Status),
		"session_id":     strings.TrimSpace(o.SessionID),
		"user_id":        strings.TrimSpace(o.UserID),
		"message":        strings.TrimSpace(o.Message),
		"final_cards":    cards,
	}
	if len(o.Metadata) > 0 {
		out["metadata"] = o.Metadata
	}
	return out
}

func normalizeOutcomeStatus(v string) string {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "completed", "success", "succeeded":
		return "completed"
	case "failed", "error":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	case "running", "pending", "queued":
		return "running"
	default:
		return ""
	}
}

func normalizeOutcomeCards(raw []any) []TaskOutcomeCard {
	if len(raw) == 0 {
		return nil
	}
	out := make([]TaskOutcomeCard, 0, len(raw))
	for _, item := range raw {
		card, ok := item.(map[string]any)
		if !ok {
			continue
		}
		id := firstNonEmpty(
			strings.TrimSpace(asString(card["id"])),
			strings.TrimSpace(asString(card["card_id"])),
		)
		front := strings.TrimSpace(asString(card["front"]))
		back := strings.TrimSpace(asString(card["back"]))
		if content, ok := card["content"].(map[string]any); ok {
			if data, ok := content["data"].(map[string]any); ok {
				front = firstNonEmpty(front, strings.TrimSpace(asString(data["front"])))
				back = firstNonEmpty(back, strings.TrimSpace(asString(data["back"])))
			}
		}
		model := strings.TrimSpace(asString(card["model"]))
		if model == "" {
			if content, ok := card["content"].(map[string]any); ok {
				model = strings.TrimSpace(asString(content["model"]))
			}
		}
		tags := normalizeStringSlice(asAnySlice(card["tags"]))
		if content, ok := card["content"].(map[string]any); ok {
			if data, ok := content["data"].(map[string]any); ok && len(tags) == 0 {
				tags = normalizeStringSlice(asAnySlice(data["tags"]))
			}
		}
		if id == "" && front == "" && back == "" {
			continue
		}
		out = append(out, TaskOutcomeCard{
			ID:     firstNonEmpty(id, fmt.Sprintf("card_%d", len(out)+1)),
			Front:  front,
			Back:   back,
			Model:  firstNonEmpty(model, "mcq"),
			Status: strings.TrimSpace(asString(card["status"])),
			Tags:   tags,
		})
	}
	return out
}

func normalizeStringSlice(raw []any) []string {
	if len(raw) == 0 {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		s := strings.TrimSpace(asString(item))
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

func asAnySlice(v any) []any {
	switch t := v.(type) {
	case []any:
		return t
	case []map[string]any:
		out := make([]any, 0, len(t))
		for _, item := range t {
			out = append(out, item)
		}
		return out
	default:
		return nil
	}
}

func asString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	default:
		return ""
	}
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}
