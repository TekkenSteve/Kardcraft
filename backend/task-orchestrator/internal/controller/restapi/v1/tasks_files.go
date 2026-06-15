package v1

import (
	"context"
	"strings"
	"time"

	"task-orchestrator/internal/usecase"
)

func resolveSessionFileContext(ctx context.Context, deps TasksDeps, sessionID string) ([]map[string]any, []string, error) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		return nil, nil, nil
	}
	events, err := deps.ReadModel.ListSessionEvents(ctx, sessionID, 2000, 0)
	if err != nil {
		return nil, nil, err
	}
	if len(events) == 0 {
		return nil, nil, nil
	}
	fileIDs := make([]string, 0)
	artifacts := make([]map[string]any, 0)
	seen := make(map[string]struct{})
	for i := len(events) - 1; i >= 0; i-- {
		payload := parsePayloadText(events[i].Payload)
		record, ok := payload.(map[string]any)
		if !ok {
			continue
		}
		for _, artifact := range extractFileArtifactsFromEventPayload(record) {
			fileID := strings.TrimSpace(asStringAny(artifact["file_id"]))
			if fileID == "" {
				continue
			}
			if _, exists := seen[fileID]; exists {
				continue
			}
			seen[fileID] = struct{}{}
			fileIDs = append(fileIDs, fileID)
			artifacts = append(artifacts, artifact)
		}
	}
	if len(fileIDs) == 0 {
		return nil, nil, nil
	}
	return artifacts, fileIDs, nil
}

func extractFileArtifactsFromEventPayload(record map[string]any) []map[string]any {
	out := make([]map[string]any, 0)
	appendFromAttachments := func(value any) {
		list, ok := value.([]any)
		if !ok {
			return
		}
		for _, entry := range list {
			item, ok := entry.(map[string]any)
			if !ok {
				continue
			}
			fileID := strings.TrimSpace(asStringAny(item["file_id"]))
			if fileID == "" {
				continue
			}
			filename := strings.TrimSpace(asStringAny(item["filename"]))
			if filename == "" {
				filename = fileID
			}
			mimeType := strings.TrimSpace(asStringAny(item["mime_type"]))
			if mimeType == "" {
				mimeType = "application/octet-stream"
			}
			size := asInt64Any(item["size"])
			if size < 0 {
				size = 0
			}
			out = append(out, map[string]any{
				"file_id":            fileID,
				"filename":           filename,
				"mime_type":          mimeType,
				"size":               size,
				"status":             "active",
				"pinned":             false,
				"index_state":        "unknown",
				"workspace_presence": "unknown",
				"last_used_at":       "",
			})
		}
	}
	appendFromFileIDs := func(value any) {
		list, ok := value.([]any)
		if !ok {
			return
		}
		for _, entry := range list {
			fileID := strings.TrimSpace(asStringAny(entry))
			if fileID == "" {
				continue
			}
			out = append(out, map[string]any{
				"file_id":            fileID,
				"filename":           fileID,
				"mime_type":          "application/octet-stream",
				"size":               int64(0),
				"status":             "active",
				"pinned":             false,
				"index_state":        "unknown",
				"workspace_presence": "unknown",
				"last_used_at":       "",
			})
		}
	}

	appendFromAttachments(record["attachments"])
	appendFromFileIDs(record["file_ids"])
	if input, ok := record["input"].(map[string]any); ok {
		appendFromAttachments(input["attachments"])
		appendFromFileIDs(input["file_ids"])
	}
	if len(out) == 0 {
		return nil
	}
	deduped := make([]map[string]any, 0, len(out))
	seen := make(map[string]struct{}, len(out))
	for _, item := range out {
		fileID := strings.TrimSpace(asStringAny(item["file_id"]))
		if fileID == "" {
			continue
		}
		if _, ok := seen[fileID]; ok {
			continue
		}
		seen[fileID] = struct{}{}
		deduped = append(deduped, item)
	}
	if len(deduped) == 0 {
		return nil
	}
	return deduped
}

func normalizeConversationHistoryFromRequest(messages []usecase.AgentMessage, maxMessages int) []usecase.AgentMessage {
	if maxMessages <= 0 {
		maxMessages = 24
	}
	normalized := make([]usecase.AgentMessage, 0, len(messages))
	for _, msg := range messages {
		role := strings.ToLower(strings.TrimSpace(msg.Role))
		if role != "user" && role != "assistant" && role != "system" {
			continue
		}
		content := strings.TrimSpace(msg.Content)
		if content == "" {
			continue
		}
		normalized = append(normalized, usecase.AgentMessage{
			Role:    role,
			Content: content,
		})
	}
	if len(normalized) > maxMessages {
		normalized = normalized[len(normalized)-maxMessages:]
	}
	return normalized
}

func buildConversationHistoryFromSession(ctx context.Context, deps TasksDeps, sessionID, userID string, maxMessages int) ([]usecase.AgentMessage, error) {
	if maxMessages <= 0 {
		maxMessages = 24
	}
	tasks, err := deps.ReadModel.ListSessionTasks(ctx, sessionID, userID)
	if err != nil {
		return nil, err
	}
	if len(tasks) == 0 {
		return nil, nil
	}
	events, err := deps.ReadModel.ListSessionEvents(ctx, sessionID, 2000, 0)
	if err != nil {
		return nil, err
	}
	eventsByTask := make(map[string][]usecase.EventRow)
	for _, ev := range events {
		taskID := ""
		if ev.TaskID != nil {
			taskID = *ev.TaskID
		}
		eventsByTask[taskID] = append(eventsByTask[taskID], ev)
	}

	messages := make([]usecase.AgentMessage, 0, len(tasks)*2)
	for _, t := range tasks {
		taskID := strings.TrimSpace(t.TaskID)
		query := strings.TrimSpace(valueFromPtr(t.Query))
		if query != "" {
			messages = append(messages, usecase.AgentMessage{
				Role:    "user",
				Content: query,
			})
		}

		assistantContent := strings.TrimSpace(ExtractResultMessage(t.Result))
		if assistantContent == "" {
			if text, _ := extractAssistantContentFromEvents(eventsByTask[taskID]); strings.TrimSpace(text) != "" {
				assistantContent = strings.TrimSpace(text)
			}
		}
		if assistantContent != "" {
			messages = append(messages, usecase.AgentMessage{
				Role:    "assistant",
				Content: assistantContent,
			})
			continue
		}
		if strings.EqualFold(valueFromPtr(t.Status), "cancelled") {
			messages = append(messages, usecase.AgentMessage{
				Role:    "assistant",
				Content: "This task was cancelled.",
			})
		}
	}

	if len(messages) > maxMessages {
		messages = messages[len(messages)-maxMessages:]
	}
	return messages, nil
}

func taskTimestampRFC3339(startedAt, completedAt *time.Time) string {
	if startedAt != nil {
		return startedAt.UTC().Format(time.RFC3339)
	}
	if completedAt != nil {
		return completedAt.UTC().Format(time.RFC3339)
	}
	return ""
}
