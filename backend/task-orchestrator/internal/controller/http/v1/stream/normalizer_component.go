package stream

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

type ResolveSessionFunc func(ctx context.Context, taskID string) (string, error)

type NormalizedEvent struct {
	WorkflowID string
	SessionID  string
	TaskID     string
	EventType  string
	Message    string
	StreamID   string
	Payload    map[string]any
}

type Normalizer struct {
	resolveSession ResolveSessionFunc
}

func NewNormalizer(resolveSession ResolveSessionFunc) *Normalizer {
	return &Normalizer{resolveSession: resolveSession}
}

func (n *Normalizer) Normalize(ctx context.Context, workflowID string, msg Entry) NormalizedEvent {
	eventType := ValueAsString(msg.Values["event_type"])
	taskID := ValueAsString(msg.Values["task_id"])
	message := ValueAsString(msg.Values["message"])
	dataStr := ValueAsString(msg.Values["data"])
	nodeName := ValueAsString(msg.Values["node_name"])
	workspaceID := ValueAsString(msg.Values["workspace_id"])

	payload := map[string]any{}
	if dataStr != "" {
		var decoded map[string]any
		if err := json.Unmarshal([]byte(dataStr), &decoded); err == nil {
			payload = decoded
			if nodeName == "" {
				if nestedNode, ok := decoded["node_name"].(string); ok {
					nodeName = strings.TrimSpace(nestedNode)
				}
			}
			if message == "" {
				if nested, ok := decoded["message"].(string); ok {
					message = nested
				}
			}
			if eventType == "" {
				if nestedType, ok := decoded["event_type"].(string); ok && strings.TrimSpace(nestedType) != "" {
					eventType = strings.TrimSpace(nestedType)
				} else if nestedType, ok := decoded["type"].(string); ok && strings.TrimSpace(nestedType) != "" {
					eventType = strings.TrimSpace(nestedType)
				}
			}
			if workspaceID == "" {
				if nestedWorkspaceID, ok := decoded["workspace_id"].(string); ok {
					workspaceID = strings.TrimSpace(nestedWorkspaceID)
				}
			}
		} else {
			payload["raw"] = dataStr
			if message == "" {
				message = dataStr
			}
		}
	}
	if eventType == "" {
		eventType = "WORKFLOW_PROGRESS"
	}

	sessionID := workspaceID
	if sessionID == "" && taskID != "" && n != nil && n.resolveSession != nil {
		if sid, err := n.resolveSession(ctx, taskID); err == nil {
			sessionID = sid
		}
	}
	if taskID == "" {
		taskID = workflowID
	}

	upperType := strings.ToUpper(strings.TrimSpace(eventType))
	switch upperType {
	case "NODE_STARTED":
		eventType = "NODE_STARTED"
		if message == "" && nodeName != "" {
			message = fmt.Sprintf("%s started", nodeName)
		}
	case "NODE_COMPLETED":
		eventType = "NODE_COMPLETED"
		if message == "" && nodeName != "" {
			message = fmt.Sprintf("%s completed", nodeName)
		}
	case "NODE_FAILED":
		eventType = "NODE_FAILED"
		if message == "" && nodeName != "" {
			message = fmt.Sprintf("%s failed", nodeName)
		}
	}
	if nodeName != "" {
		payload["node_name"] = nodeName
		payload["event_name"] = nodeName
	}
	if _, ok := payload["event_type"]; !ok {
		payload["event_type"] = eventType
	}
	if _, ok := payload["message"]; !ok && message != "" {
		payload["message"] = message
	}
	if workspaceID != "" {
		payload["workspace_id"] = workspaceID
	}

	return NormalizedEvent{
		WorkflowID: workflowID,
		SessionID:  sessionID,
		TaskID:     taskID,
		EventType:  eventType,
		Message:    message,
		StreamID:   msg.ID,
		Payload:    payload,
	}
}
