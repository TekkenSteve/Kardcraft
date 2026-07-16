package apkgexport

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"task-orchestrator/internal/usecase"
)

// exportWorkspace is a narrow typed projection of a session workspace. The
// storage representation remains independent from the APKG export protocol.
type exportWorkspace struct {
	TemplateID string       `json:"template_id"`
	Cards      []exportCard `json:"cards"`
}

type exportCard struct {
	Content struct {
		Data map[string]json.RawMessage `json:"data"`
	} `json:"content"`
	EditState struct {
		Status string `json:"status"`
	} `json:"edit_state"`
}

func loadWorkspace(ctx context.Context, readModel usecase.ReadModel, sessionID string) (exportWorkspace, error) {
	raw, err := readModel.LoadWorkspace(ctx, sessionID)
	if err != nil {
		return exportWorkspace{}, fmt.Errorf("load workspace: %w", err)
	}
	encoded, err := json.Marshal(raw)
	if err != nil {
		return exportWorkspace{}, fmt.Errorf("encode workspace: %w", err)
	}
	var workspace exportWorkspace
	if err := json.Unmarshal(encoded, &workspace); err != nil {
		return exportWorkspace{}, fmt.Errorf("decode workspace: %w", err)
	}
	return workspace, nil
}

func (w exportWorkspace) confirmedCards() []exportCard {
	confirmed := make([]exportCard, 0, len(w.Cards))
	for _, card := range w.Cards {
		if strings.EqualFold(strings.TrimSpace(card.EditState.Status), "confirmed") {
			confirmed = append(confirmed, card)
		}
	}
	return confirmed
}

func (c exportCard) exportFields(fieldNames []string, deckName string) (map[string]string, []string) {
	fields := make(map[string]string, len(fieldNames))
	tags := decodeTags(c.Content.Data["tags"])
	for _, fieldName := range fieldNames {
		switch fieldName {
		case "Front":
			fields[fieldName] = firstNonEmpty(decodeString(c.Content.Data["Front"]), decodeString(c.Content.Data["front"]))
		case "Back":
			fields[fieldName] = firstNonEmpty(decodeString(c.Content.Data["Back"]), decodeString(c.Content.Data["back"]))
		case "Deck":
			fields[fieldName] = firstNonEmpty(decodeString(c.Content.Data["Deck"]), deckName)
		case "Tags":
			fields[fieldName] = firstNonEmpty(decodeString(c.Content.Data["Tags"]), strings.Join(tags, " "))
		default:
			fields[fieldName] = decodeString(c.Content.Data[fieldName])
		}
	}
	return fields, tags
}

func decodeString(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var value string
	if json.Unmarshal(raw, &value) == nil {
		return strings.TrimSpace(value)
	}
	return ""
}

func decodeTags(raw json.RawMessage) []string {
	if len(raw) == 0 {
		return nil
	}
	var list []string
	if json.Unmarshal(raw, &list) == nil {
		return sortedTags(list)
	}
	value := decodeString(raw)
	if value == "" {
		return nil
	}
	return sortedTags(strings.FieldsFunc(value, func(character rune) bool {
		return character == ',' || character == ';' || character == ' '
	}))
}
