package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"

	"task-orchestrator/internal/infrastructure/persistence"
	redissvc "task-orchestrator/internal/infrastructure/redis"
)

const usageSchemaVersion = "1"

func (s *Server) appendTimeline(workflowID, sessionID, eventType, message string, payload any) {
	s.appendTimelineWithStreamID(workflowID, sessionID, eventType, message, "", payload)
}

func (s *Server) appendTimelineWithStreamID(workflowID, sessionID, eventType, message, streamID string, payload any) {
	if strings.TrimSpace(streamID) == "" {
		streamID = fmt.Sprintf("%d", time.Now().UTC().UnixNano())
	}
	s.mu.Lock()
	streamSet, ok := s.seenStreamIDs[workflowID]
	if !ok {
		streamSet = make(map[string]struct{})
		s.seenStreamIDs[workflowID] = streamSet
	}
	if _, exists := streamSet[streamID]; exists {
		atomic.AddInt64(&s.duplicateDrops, 1)
		s.mu.Unlock()
		return
	}
	streamSet[streamID] = struct{}{}
	if len(streamSet) > 4000 {
		// Keep memory bounded; stale ids are acceptable to evict.
		s.seenStreamIDs[workflowID] = map[string]struct{}{streamID: {}}
	}
	s.mu.Unlock()

	ev := TimelineEvent{
		ID:         s.nextEventID(),
		Type:       eventType,
		Message:    message,
		Timestamp:  nowRFC3339(),
		WorkflowID: workflowID,
		TaskID:     workflowID,
		StreamID:   streamID,
		Payload:    payload,
	}
	payloadText := ""
	if payload != nil {
		if b, err := json.Marshal(payload); err == nil {
			payloadText = string(b)
		}
	}
	if s.sessionDB != nil && sessionID != "" {
		_ = s.sessionDB.InsertEvent(
			context.Background(),
			sessionID,
			workflowID,
			workflowID,
			eventType,
			message,
			payloadText,
			streamID,
			time.Now().UTC(),
		)
	}

	s.mu.Lock()
	s.timelineByWorkflow[workflowID] = append(s.timelineByWorkflow[workflowID], ev)
	if len(s.timelineByWorkflow[workflowID]) > maxTimelineEventsInMemory {
		s.timelineByWorkflow[workflowID] = append([]TimelineEvent(nil), s.timelineByWorkflow[workflowID][len(s.timelineByWorkflow[workflowID])-maxTimelineEventsInMemory:]...)
	}
	subs := make([]chan sseEvent, 0)
	if byWorkflow, ok := s.subscribers[workflowID]; ok {
		for _, ch := range byWorkflow {
			subs = append(subs, ch)
		}
	}
	s.mu.Unlock()

	payloadMap := map[string]any{
		"type":        eventType,
		"workflow_id": workflowID,
		"task_id":     workflowID,
		"message":     message,
		"timestamp":   ev.Timestamp,
		"stream_id":   ev.StreamID,
	}
	if payload != nil {
		payloadMap["payload"] = payload
	}
	buf, _ := json.Marshal(payloadMap)
	for _, ch := range subs {
		select {
		case ch <- sseEvent{id: ev.ID, event: eventType, payload: buf}:
		default:
		}
	}
}

func (s *Server) subscribe(workflowID string) (int, chan sseEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.subscriberSeq++
	id := s.subscriberSeq
	if _, ok := s.subscribers[workflowID]; !ok {
		s.subscribers[workflowID] = make(map[int]chan sseEvent)
	}
	ch := make(chan sseEvent, 128)
	s.subscribers[workflowID][id] = ch
	return id, ch
}

func (s *Server) unsubscribe(workflowID string, subscriberID int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if subs, ok := s.subscribers[workflowID]; ok {
		if ch, ok := subs[subscriberID]; ok {
			delete(subs, subscriberID)
			close(ch)
		}
		if len(subs) == 0 {
			delete(s.subscribers, workflowID)
		}
	}
}

func (s *Server) ensureWorkflowStreamReader(workflowID string) {
	if s.redisSvc == nil || !s.redisSvc.Enabled() {
		return
	}
	s.mu.Lock()
	if _, exists := s.streamReaders[workflowID]; exists {
		s.mu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.streamReaders[workflowID] = cancel
	s.mu.Unlock()

	go func() {
		defer func() {
			s.mu.Lock()
			if _, ok := s.streamReaders[workflowID]; ok {
				delete(s.streamReaders, workflowID)
			}
			s.mu.Unlock()
		}()
		s.subscribeRedisStream(ctx, workflowID)
	}()
}

func (s *Server) stopWorkflowStreamReader(workflowID string) {
	s.mu.Lock()
	cancel, ok := s.streamReaders[workflowID]
	if ok {
		delete(s.streamReaders, workflowID)
	}
	delete(s.seenStreamIDs, workflowID)
	s.mu.Unlock()
	if ok {
		cancel()
	}
}

func (s *Server) sseHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
	if workflowID == "" {
		http.Error(w, "workflow_id required", http.StatusBadRequest)
		return
	}
	userID := userIDFromContext(r.Context())
	if !s.authorizeTaskAccess(r.Context(), userID, workflowID) {
		writeAPIError(w, http.StatusForbidden, errCodeAuthzDenied, "access denied for workflow stream", map[string]any{
			"workflow_id": workflowID,
		})
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set("Transfer-Encoding", "chunked")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	subscriberID, events := s.subscribe(workflowID)
	defer s.unsubscribe(workflowID, subscriberID)
	s.ensureWorkflowStreamReader(workflowID)

	fmt.Fprintf(w, ": %s\n\n", strings.Repeat(" ", 1024))
	initEvent := map[string]any{
		"type":        "STATUS_UPDATE",
		"workflow_id": workflowID,
		"message":     "Stream connected",
		"timestamp":   nowRFC3339(),
	}
	buf, _ := json.Marshal(initEvent)
	fmt.Fprintf(w, "event: STATUS_UPDATE\ndata: %s\n\n", string(buf))
	flusher.Flush()

	s.mu.RLock()
	backlog := append([]TimelineEvent(nil), s.timelineByWorkflow[workflowID]...)
	s.mu.RUnlock()
	for _, ev := range backlog {
		payload := map[string]any{
			"type":        ev.Type,
			"workflow_id": ev.WorkflowID,
			"task_id":     ev.TaskID,
			"message":     ev.Message,
			"timestamp":   ev.Timestamp,
			"stream_id":   ev.StreamID,
		}
		if ev.Payload != nil {
			payload["payload"] = ev.Payload
		}
		b, _ := json.Marshal(payload)
		fmt.Fprintf(w, "event: %s\ndata: %s\n\n", ev.Type, string(b))
	}
	flusher.Flush()

	ctx := r.Context()
	heartbeat := time.NewTicker(10 * time.Second)
	defer heartbeat.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-heartbeat.C:
			// Keep SSE connection alive through proxy idle timeouts.
			// Comment frames are ignored by clients but refresh socket activity.
			fmt.Fprintf(w, ": ping %d\n\n", time.Now().UTC().Unix())
			flusher.Flush()
		case ev, ok := <-events:
			if !ok {
				return
			}
			fmt.Fprintf(w, "id: %d\n", ev.id)
			fmt.Fprintf(w, "event: %s\n", ev.event)
			fmt.Fprintf(w, "data: %s\n\n", string(ev.payload))
			flusher.Flush()
		}
	}
}

func (s *Server) subscribeRedisStream(ctx context.Context, workflowID string) {
	if s.redisSvc == nil || !s.redisSvc.Enabled() {
		return
	}
	// Start from the beginning when there is no checkpoint yet.
	// Using "$" can miss early events if the reader starts after workflow emits first entries.
	lastID := "0-0"
	if checkpoint, err := s.redisSvc.GetCheckpoint(ctx, workflowID); err == nil && strings.TrimSpace(checkpoint) != "" {
		lastID = strings.TrimSpace(checkpoint)
	}
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		entries, nextID, err := s.redisSvc.StreamRead(ctx, workflowID, lastID, 32, 5*time.Second)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			if err == redis.Nil {
				continue
			}
			log.Printf("redis stream read error for %s: %v", redissvc.StreamKey(workflowID), err)
			time.Sleep(time.Second)
			continue
		}
		lastID = nextID
		for _, msg := range entries {
			eventType := valueAsString(msg.Values["event_type"])
			taskID := valueAsString(msg.Values["task_id"])
			message := valueAsString(msg.Values["message"])
			dataStr := valueAsString(msg.Values["data"])
			nodeName := valueAsString(msg.Values["node_name"])
			workspaceID := valueAsString(msg.Values["workspace_id"])
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
			sessionID := ""
			if workspaceID != "" {
				sessionID = workspaceID
			} else if taskID != "" && s.sessionDB != nil {
				if sid, err := s.sessionDB.GetTaskSession(ctx, taskID); err == nil {
					sessionID = sid
				}
			}
			if taskID == "" {
				taskID = workflowID
			}
			if strings.EqualFold(strings.TrimSpace(eventType), "LLM_USAGE") && s.sessionDB != nil {
				row, ok, reason := buildUsageLedgerRow(payload, workflowID, taskID, sessionID)
				if ok {
					inserted, err := s.sessionDB.InsertLLMUsage(ctx, row)
					if err != nil {
						atomic.AddInt64(&s.llmUsageFailed, 1)
						log.Printf("llm usage ingest failed workflow_id=%s task_id=%s stream_id=%s err=%v", workflowID, taskID, msg.ID, err)
					} else if !inserted {
						atomic.AddInt64(&s.llmUsageDeduped, 1)
						log.Printf("llm usage duplicate dropped workflow_id=%s task_id=%s stream_id=%s idempotency_key=%s", workflowID, taskID, msg.ID, row.IdempotencyKey)
					} else {
						atomic.AddInt64(&s.llmUsageIngested, 1)
					}
				} else {
					if reason == "schema_mismatch" {
						atomic.AddInt64(&s.llmUsageSchemaMismatch, 1)
					} else {
						atomic.AddInt64(&s.llmUsageInvalid, 1)
					}
					log.Printf("llm usage payload invalid workflow_id=%s task_id=%s stream_id=%s reason=%s payload=%v", workflowID, taskID, msg.ID, reason, payload)
				}
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
			s.appendTimelineWithStreamID(workflowID, sessionID, eventType, message, msg.ID, payload)
		}
		if strings.TrimSpace(lastID) != "" {
			_ = s.redisSvc.SetCheckpoint(ctx, workflowID, lastID)
		}
	}
}

func valueAsString(v any) string {
	if v == nil {
		return ""
	}
	switch typed := v.(type) {
	case string:
		return strings.TrimSpace(typed)
	case []byte:
		return strings.TrimSpace(string(typed))
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", typed))
	}
}

func buildUsageLedgerRow(payload map[string]any, workflowID, fallbackTaskID, fallbackSessionID string) (persistence.UsageLedgerRow, bool, string) {
	row := persistence.UsageLedgerRow{
		SchemaVersion:    normalizedString(payload["schema_version"], "1"),
		IdempotencyKey:   normalizedString(payload["idempotency_key"], ""),
		TaskID:           normalizedString(payload["task_id"], fallbackTaskID),
		WorkflowID:       normalizedString(payload["workflow_id"], workflowID),
		SessionID:        normalizedString(payload["session_id"], fallbackSessionID),
		UserID:           normalizedString(payload["user_id"], ""),
		Intent:           normalizedString(payload["intent"], ""),
		Provider:         normalizedString(payload["provider"], ""),
		Model:            normalizedString(payload["model"], ""),
		PromptTokens:     asInt(payload["prompt_tokens"]),
		CompletionTokens: asInt(payload["completion_tokens"]),
		CacheReadTokens:  asInt(payload["cache_read_tokens"]),
		CacheWriteTokens: asInt(payload["cache_write_tokens"]),
		TotalTokens:      asInt(payload["total_tokens"]),
		InputCostUSD:     asFloat(payload["input_cost_usd"]),
		OutputCostUSD:    asFloat(payload["output_cost_usd"]),
		CacheCostUSD:     asFloat(payload["cache_cost_usd"]),
		TotalCostUSD:     asFloat(payload["total_cost_usd"]),
		Estimated:        asBool(payload["estimated"]),
		Source:           normalizedString(payload["source"], ""),
		ExternalRequestID: normalizedString(
			firstAny(payload["external_request_id"], payload["request_id"], payload["llm_response_id"]),
			"",
		),
		Metadata: asMap(payload["metadata"]),
	}
	if row.SchemaVersion != usageSchemaVersion {
		return persistence.UsageLedgerRow{}, false, "schema_mismatch"
	}
	if createdAt := normalizedString(payload["created_at"], ""); createdAt != "" {
		if parsed, err := time.Parse(time.RFC3339Nano, createdAt); err == nil {
			row.CreatedAt = parsed
		}
	}
	if row.IdempotencyKey == "" {
		row.IdempotencyKey = normalizedString(payload["stream_id"], "")
	}
	if row.IdempotencyKey == "" && row.ExternalRequestID != "" && row.TaskID != "" {
		row.IdempotencyKey = row.TaskID + ":" + row.ExternalRequestID
	}
	if row.IdempotencyKey == "" {
		return persistence.UsageLedgerRow{}, false, "missing_idempotency_key"
	}
	if row.TaskID == "" || row.Provider == "" || row.Model == "" {
		return persistence.UsageLedgerRow{}, false, "missing_required_fields"
	}
	if row.TotalTokens == 0 {
		row.TotalTokens = row.PromptTokens + row.CompletionTokens
	}
	return row, true, ""
}

func normalizedString(v any, fallback string) string {
	s := strings.TrimSpace(valueAsString(v))
	if s == "" {
		return fallback
	}
	return s
}

func asMap(v any) map[string]any {
	if v == nil {
		return nil
	}
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

func asInt(v any) int {
	switch t := v.(type) {
	case int:
		return t
	case int32:
		return int(t)
	case int64:
		return int(t)
	case float32:
		return int(t)
	case float64:
		return int(t)
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return int(i)
		}
	case string:
		if n, err := strconv.Atoi(strings.TrimSpace(t)); err == nil {
			return n
		}
	}
	return 0
}

func asFloat(v any) float64 {
	switch t := v.(type) {
	case float64:
		return t
	case float32:
		return float64(t)
	case int:
		return float64(t)
	case int64:
		return float64(t)
	case json.Number:
		if f, err := t.Float64(); err == nil {
			return f
		}
	case string:
		if f, err := strconv.ParseFloat(strings.TrimSpace(t), 64); err == nil {
			return f
		}
	}
	return 0
}

func asBool(v any) bool {
	switch t := v.(type) {
	case bool:
		return t
	case string:
		b, err := strconv.ParseBool(strings.TrimSpace(t))
		return err == nil && b
	case int:
		return t != 0
	case float64:
		return t != 0
	default:
		return false
	}
}

func firstAny(values ...any) any {
	for _, v := range values {
		if strings.TrimSpace(valueAsString(v)) != "" {
			return v
		}
	}
	return nil
}
