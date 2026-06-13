package v1

import (
	"encoding/json"
	"strings"
	"time"
)

func normalizeSessionStatusPtr(status *string) string {
	if status == nil {
		return "idle"
	}
	switch strings.ToLower(strings.TrimSpace(*status)) {
	case "pending", "queued", "running":
		return "running"
	case "failed", "error":
		return "failed"
	case "cancelled", "canceled":
		return "cancelled"
	case "paused":
		return "paused"
	case "completed", "success":
		return "completed"
	default:
		return "idle"
	}
}

func valueFromPtr(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}

func parsePayloadText(raw *string) any {
	if raw == nil || *raw == "" {
		return nil
	}
	var out any
	if err := json.Unmarshal([]byte(*raw), &out); err == nil {
		return out
	}
	return *raw
}

func NormalizeWorkspaceResponse(raw map[string]any, sessionID string) map[string]any {
	out := map[string]any{"session_id": sessionID, "version": 0, "status": "not_started", "card_count": 0, "cards": []map[string]any{}, "projection_status": "empty"}
	if raw == nil {
		return out
	}
	if sid, ok := raw["session_id"].(string); ok && strings.TrimSpace(sid) != "" {
		out["session_id"] = sid
	}
	if v, ok := raw["version"].(float64); ok {
		out["version"] = int(v)
	} else if v, ok := raw["version"].(int); ok {
		out["version"] = v
	}
	if status, ok := raw["status"].(string); ok && strings.TrimSpace(status) != "" {
		out["status"] = status
	}
	if templateID, ok := raw["template_id"].(string); ok && strings.TrimSpace(templateID) != "" {
		out["template_id"] = strings.TrimSpace(templateID)
	}
	if selected, ok := raw["selected_question_type"].(string); ok && strings.TrimSpace(selected) != "" {
		out["selected_question_type"] = strings.TrimSpace(selected)
	}
	if supported := normalizeStringSliceAny(raw["supported_question_types"]); len(supported) > 0 {
		out["supported_question_types"] = supported
	}
	cardsRaw, _ := raw["cards"].([]any)
	cards := make([]map[string]any, 0, len(cardsRaw))
	now := time.Now().UTC().Format(time.RFC3339)
	for _, entry := range cardsRaw {
		card, ok := normalizeWorkspaceCard(entry, now)
		if ok {
			cards = append(cards, card)
		}
	}
	out["cards"] = cards
	out["card_count"] = len(cards)
	if len(cards) > 0 {
		out["projection_status"] = "hydrated"
	}
	return out
}

func normalizeStringSliceAny(v any) []string {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		s, ok := item.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		out = append(out, s)
	}
	return out
}

func normalizeWorkspaceCard(entry any, fallbackTime string) (map[string]any, bool) {
	card, ok := entry.(map[string]any)
	if !ok {
		return nil, false
	}

	cardID := strings.TrimSpace(firstNonEmptyStringAny(card["card_id"], card["id"], card["temp_id"]))
	if cardID == "" {
		return nil, false
	}

	content := asMapAny(card["content"])
	contentData := asMapAny(content["data"])
	front := strings.TrimSpace(firstNonEmptyStringAny(contentData["front"], content["front"]))
	back := strings.TrimSpace(firstNonEmptyStringAny(contentData["back"], content["back"]))

	data := map[string]any{
		"front": front,
		"back":  back,
		"tags":  normalizeStringSliceAny(contentData["tags"]),
	}
	if len(data["tags"].([]string)) == 0 {
		data["tags"] = normalizeStringSliceAny(content["tags"])
	}
	data["concepts"] = normalizeStringSliceAny(contentData["concepts"])
	if len(data["concepts"].([]string)) == 0 {
		data["concepts"] = normalizeStringSliceAny(content["concepts"])
	}

	contentOut := map[string]any{
		"version": asIntAny(firstNonEmptyAny(content["version"], card["version"])),
		"model":   strings.TrimSpace(firstNonEmptyStringAny(content["model"], card["model"])),
		"data":    data,
	}
	if asIntAny(contentOut["version"]) <= 0 {
		contentOut["version"] = 1
	}
	if contentOut["model"] == "" {
		contentOut["model"] = "mcq"
	}
	if media, ok := content["media"].([]any); ok {
		contentOut["media"] = media
	} else if media, ok := card["media"].([]any); ok {
		contentOut["media"] = media
	} else {
		contentOut["media"] = []any{}
	}

	status := normalizeWorkspaceCardStatus(strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["status"],
		card["status"],
	)))
	if status == "" {
		return nil, false
	}
	editStateOut := map[string]any{"status": status}
	if lockedBy := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["locked_by"],
		card["locked_by"],
	)); lockedBy != "" {
		editStateOut["locked_by"] = lockedBy
	}
	if lockedAt := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["locked_at"],
		card["locked_at"],
	)); lockedAt != "" {
		editStateOut["locked_at"] = lockedAt
	}
	if expiresAt := strings.TrimSpace(firstNonEmptyStringAny(
		asMapAny(card["edit_state"])["expires_at"],
		card["lock_expires"],
	)); expiresAt != "" {
		editStateOut["expires_at"] = expiresAt
	}

	meta := asMapAny(card["meta"])
	createdAt := strings.TrimSpace(firstNonEmptyStringAny(meta["created_at"], card["created_at"], fallbackTime))
	modifiedAt := strings.TrimSpace(firstNonEmptyStringAny(meta["modified_at"], card["modified_at"], fallbackTime))
	metaOut := map[string]any{
		"created_at":   createdAt,
		"modified_at":  modifiedAt,
		"manual_edits": asIntAny(firstNonEmptyAny(meta["manual_edits"], card["manual_edits"])),
	}

	userID := strings.TrimSpace(firstNonEmptyStringAny(card["user_id"], card["owner"], "system"))
	suggestedQuestionType := strings.TrimSpace(firstNonEmptyStringAny(card["suggested_question_type"], contentOut["model"]))

	out := map[string]any{
		"id":                      cardID,
		"user_id":                 userID,
		"card_id":                 cardID,
		"suggested_question_type": suggestedQuestionType,
		"content":                 contentOut,
		"edit_state":              editStateOut,
		"concepts":                data["concepts"],
		"meta":                    metaOut,
	}
	return out, true
}

func normalizeWorkspaceCardStatus(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "draft", "output_draft":
		return "draft"
	case "ai_editing":
		return "ai_editing"
	case "user_editing":
		return "user_editing"
	case "confirmed", "output_confirmed":
		return "confirmed"
	default:
		return ""
	}
}

func asMapAny(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func asIntAny(v any) int {
	switch val := v.(type) {
	case int:
		return val
	case int32:
		return int(val)
	case int64:
		return int(val)
	case float64:
		return int(val)
	default:
		return 0
	}
}

func firstNonEmptyStringAny(values ...any) string {
	for _, value := range values {
		if s, ok := value.(string); ok {
			if strings.TrimSpace(s) != "" {
				return strings.TrimSpace(s)
			}
		}
	}
	return ""
}

func firstNonEmptyAny(values ...any) any {
	for _, value := range values {
		if value == nil {
			continue
		}
		switch typed := value.(type) {
		case string:
			if strings.TrimSpace(typed) == "" {
				continue
			}
		}
		return value
	}
	return nil
}
