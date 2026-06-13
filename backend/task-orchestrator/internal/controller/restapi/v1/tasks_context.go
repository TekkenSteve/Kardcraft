package v1

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/TekkenSteve/GoAgent/entity"
)

const (
	workspaceIdleThreshold = 6 * time.Hour
	workspaceTTLThreshold  = 72 * time.Hour
)

func normalizeFilePolicy(raw string) string {
	policy := strings.ToLower(strings.TrimSpace(raw))
	switch policy {
	case "", "inherit":
		return "inherit"
	case "explicit_only", "exclude":
		return policy
	default:
		return "inherit"
	}
}

func applyFilePolicy(policy string, inheritedFileIDs, explicitFileIDs []string) []string {
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)

	switch policy {
	case "explicit_only":
		return normalizedExplicit
	case "exclude":
		excluded := make(map[string]struct{}, len(normalizedExplicit))
		for _, fileID := range normalizedExplicit {
			excluded[fileID] = struct{}{}
		}
		out := make([]string, 0, len(normalizedInherited))
		for _, fileID := range normalizedInherited {
			if _, deny := excluded[fileID]; deny {
				continue
			}
			out = append(out, fileID)
		}
		return out
	case "inherit":
		fallthrough
	default:
		out := make([]string, 0, len(normalizedExplicit)+len(normalizedInherited))
		seen := make(map[string]struct{}, len(normalizedExplicit)+len(normalizedInherited))
		for _, fileID := range normalizedExplicit {
			if _, ok := seen[fileID]; ok {
				continue
			}
			seen[fileID] = struct{}{}
			out = append(out, fileID)
		}
		for _, fileID := range normalizedInherited {
			if _, ok := seen[fileID]; ok {
				continue
			}
			seen[fileID] = struct{}{}
			out = append(out, fileID)
		}
		return out
	}
}

func dedupeNonEmptyStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		v := strings.TrimSpace(value)
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func buildContextEnvelope(
	ctx context.Context,
	deps TasksDeps,
	userID string,
	sessionID string,
	query string,
	filePolicy string,
	base map[string]any,
	conversationHistory []entity.Message,
	sessionFileArtifacts []map[string]any,
	explicitFileIDs []string,
	inheritedFileIDs []string,
	effectiveFileIDs []string,
) map[string]any {
	envelope := map[string]any{}
	for key, value := range base {
		envelope[key] = value
	}
	envelope["schema_version"] = "context-envelope.v1"

	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedEffective := dedupeNonEmptyStrings(effectiveFileIDs)
	policy := normalizeFilePolicy(filePolicy)

	envelope["request"] = map[string]any{
		"session_id":   sessionID,
		"user_id":      userID,
		"user_message": strings.TrimSpace(query),
		"intent_hint":  "",
	}

	recentMessages := make([]map[string]any, 0, minInt(8, len(conversationHistory)))
	start := 0
	if len(conversationHistory) > 8 {
		start = len(conversationHistory) - 8
	}
	for _, msg := range conversationHistory[start:] {
		recentMessages = append(recentMessages, map[string]any{
			"role":    msg.Role,
			"content": msg.Content,
		})
	}
	envelope["history"] = map[string]any{
		"message_count":      len(conversationHistory),
		"recent_turn_window": 8,
		"messages":           recentMessages,
		"summary":            "",
	}

	workspaceSummary := map[string]any{"available": false}
	cardsSummary := map[string]any{
		"latest_cards": []map[string]any{},
		"card_summary": "",
	}
	knowledgeState := map[string]any{
		"rag_workspace_id":   sessionID,
		"workspace_recycled": false,
		"last_query_status":  "unknown",
		"last_query_reason":  "",
	}
	if deps.ReadModel != nil && deps.ReadModel.Ready() {
		workspace, err := deps.ReadModel.LoadWorkspace(ctx, sessionID)
		if err == nil && workspace != nil {
			workspaceSummary["available"] = true
			if status := strings.TrimSpace(asStringAny(workspace["status"])); status != "" {
				workspaceSummary["status"] = status
				if status == "recycled" {
					knowledgeState["workspace_recycled"] = true
				}
			}
			lifecycleState, updatedAt, ageHours := deriveWorkspaceLifecycleState(workspace, time.Now().UTC())
			workspaceSummary["lifecycle_state"] = lifecycleState
			if updatedAt != "" {
				workspaceSummary["updated_at"] = updatedAt
			}
			workspaceSummary["age_hours"] = ageHours
			workspaceSummary["ttl_policy"] = map[string]any{
				"idle_threshold_hours": int(workspaceIdleThreshold.Hours()),
				"ttl_threshold_hours":  int(workspaceTTLThreshold.Hours()),
			}
			if lifecycleState == "recycled" {
				knowledgeState["workspace_recycled"] = true
			}
			if lifecycleState == "ttl_expired" {
				knowledgeState["last_query_reason"] = "workspace_ttl_expired"
			}
			if version := asInt64Any(workspace["version"]); version > 0 {
				workspaceSummary["version"] = version
			}
			if cards, ok := workspace["cards"].([]any); ok {
				workspaceSummary["card_count"] = len(cards)
				sampledCards := make([]map[string]any, 0, minInt(5, len(cards)))
				for _, card := range cards {
					cardMap, ok := card.(map[string]any)
					if !ok {
						continue
					}
					sampledCards = append(sampledCards, map[string]any{
						"id":    strings.TrimSpace(asStringAny(cardMap["id"])),
						"title": strings.TrimSpace(asStringAny(cardMap["title"])),
						"type":  strings.TrimSpace(asStringAny(cardMap["type"])),
					})
					if len(sampledCards) >= 5 {
						break
					}
				}
				cardsSummary["latest_cards"] = sampledCards
				cardsSummary["card_summary"] = fmt.Sprintf("%d cards in session workspace", len(cards))
			}
		}
	}

	envelope["artifacts"] = map[string]any{
		"files":              sessionFileArtifacts,
		"cards":              cardsSummary,
		"explicit_file_ids":  normalizedExplicit,
		"inherited_file_ids": normalizedInherited,
		"effective_file_ids": normalizedEffective,
		"workspace":          workspaceSummary,
	}

	envelope["knowledge_state"] = knowledgeState
	envelope["tool_capabilities"] = []string{
		"list_history_files",
		"search_ragix",
		"fetch_file_excerpt",
		"index_file_to_ragix",
		"list_history_cards",
	}
	envelope["policy"] = map[string]any{
		"disclosure_mode":             "progressive",
		"max_new_file_fetch_per_turn": 3,
		"max_excerpt_chars_per_turn":  16000,
	}

	envelope["file_resolution"] = map[string]any{
		"policy":               policy,
		"inherited_file_ids":   normalizedInherited,
		"explicit_file_ids":    normalizedExplicit,
		"effective_file_ids":   normalizedEffective,
		"effective_file_count": len(normalizedEffective),
	}
	return enforceContextEnvelopeSchema(envelope)
}

func deriveWorkspaceLifecycleState(workspace map[string]any, now time.Time) (string, string, float64) {
	if workspace == nil {
		return "idle", "", 0
	}
	status := strings.ToLower(strings.TrimSpace(asStringAny(workspace["status"])))
	if status == "recycled" {
		return "recycled", strings.TrimSpace(asStringAny(workspace["updated_at"])), 0
	}

	updatedAtRaw := strings.TrimSpace(asStringAny(workspace["updated_at"]))
	if updatedAtRaw == "" {
		if status == "active" {
			return "active", "", 0
		}
		return "idle", "", 0
	}
	updatedAt, err := time.Parse(time.RFC3339, updatedAtRaw)
	if err != nil {
		if status == "active" {
			return "active", updatedAtRaw, 0
		}
		return "idle", updatedAtRaw, 0
	}

	age := now.Sub(updatedAt.UTC())
	if age < 0 {
		age = 0
	}
	ageHours := float64(int(age.Hours()*100)) / 100.0
	switch {
	case age >= workspaceTTLThreshold:
		return "ttl_expired", updatedAt.UTC().Format(time.RFC3339), ageHours
	case age >= workspaceIdleThreshold:
		return "idle", updatedAt.UTC().Format(time.RFC3339), ageHours
	default:
		return "active", updatedAt.UTC().Format(time.RFC3339), ageHours
	}
}

func enforceContextEnvelopeSchema(envelope map[string]any) map[string]any {
	if envelope == nil {
		envelope = map[string]any{}
	}
	schemaVersion := strings.TrimSpace(asStringAny(envelope["schema_version"]))
	if schemaVersion == "" {
		schemaVersion = "context-envelope.v1"
	}
	envelope["schema_version"] = schemaVersion

	ensureMap := func(key string) map[string]any {
		raw, ok := envelope[key]
		if !ok {
			m := map[string]any{}
			envelope[key] = m
			return m
		}
		if m, ok := raw.(map[string]any); ok {
			return m
		}
		m := map[string]any{}
		envelope[key] = m
		return m
	}
	for _, key := range []string{"request", "history", "artifacts", "knowledge_state", "policy", "file_resolution"} {
		ensureMap(key)
	}

	compatibility := map[string]any{
		"unknown_fields_preserved": true,
		"normalization_strategy":   "best_effort",
	}
	if raw, ok := envelope["compatibility"].(map[string]any); ok {
		for k, v := range compatibility {
			if _, exists := raw[k]; !exists {
				raw[k] = v
			}
		}
		envelope["compatibility"] = raw
	} else {
		envelope["compatibility"] = compatibility
	}

	capabilities := []string{}
	switch raw := envelope["tool_capabilities"].(type) {
	case []string:
		capabilities = append(capabilities, raw...)
	case []any:
		for _, item := range raw {
			v := strings.TrimSpace(asStringAny(item))
			if v == "" {
				continue
			}
			capabilities = append(capabilities, v)
		}
	}
	if len(capabilities) == 0 {
		capabilities = []string{
			"list_history_files",
			"search_ragix",
			"fetch_file_excerpt",
			"index_file_to_ragix",
			"list_history_cards",
		}
	}
	envelope["tool_capabilities"] = dedupeNonEmptyStrings(capabilities)
	return envelope
}
