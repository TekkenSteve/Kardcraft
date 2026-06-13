package restapi

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync/atomic"
	"task-orchestrator/internal/usecase"
	"time"
)

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
		s.seenStreamIDs[workflowID] = map[string]struct{}{streamID: {}}
	}
	s.mu.Unlock()

	runID := s.resolveRunID(context.Background(), workflowID, payload)
	if runID == "" {
		atomic.AddInt64(&s.invalidRuntimeEvents, 1)
		return
	}
	if sessionID == "" && s.readModel != nil {
		if resolvedSessionID, err := s.readModel.GetTaskSession(context.Background(), workflowID); err == nil {
			sessionID = strings.TrimSpace(resolvedSessionID)
		}
	}
	occurredAt := nowRFC3339()
	seq := s.nextRunSeq(runID)
	eventID := s.nextEventID()
	payloadMap := map[string]any{}
	if typed, ok := payload.(map[string]any); ok && typed != nil {
		for key, value := range typed {
			payloadMap[key] = value
		}
	}
	if message != "" {
		payloadMap["message"] = message
	}
	if _, ok := payloadMap["event_type"]; !ok {
		payloadMap["event_type"] = eventType
	}
	if _, ok := payloadMap["workflow_id"]; !ok {
		payloadMap["workflow_id"] = workflowID
	}
	if _, ok := payloadMap["run_id"]; !ok {
		payloadMap["run_id"] = runID
	}
	if sessionID != "" {
		payloadMap["session_id"] = sessionID
	}
	correlationID := correlationIDFromPayload(payloadMap, workflowID, runID)
	if correlationID == "" {
		atomic.AddInt64(&s.invalidRuntimeEvents, 1)
		return
	}
	payloadMap["correlation_id"] = correlationID
	payloadMap["event_id"] = fmt.Sprintf("%d", eventID)
	payloadMap["schema_version"] = 1

	ev := TimelineEvent{
		ID:         eventID,
		Type:       eventType,
		Message:    message,
		Timestamp:  occurredAt,
		WorkflowID: workflowID,
		RunID:      runID,
		SessionID:  sessionID,
		Seq:        seq,
		TaskID:     workflowID,
		StreamID:   streamID,
		Payload:    payloadMap,
	}
	envelope := map[string]any{
		"schema_version": 1,
		"correlation_id": correlationID,
		"event_id":       fmt.Sprintf("%d", eventID),
		"run_id":         runID,
		"workflow_id":    workflowID,
		"session_id":     sessionID,
		"seq":            seq,
		"occurred_at":    occurredAt,
		"event_type":     eventType,
		"stream_id":      streamID,
		"payload":        payloadMap,
	}
	payloadText := ""
	if b, err := json.Marshal(envelope); err == nil {
		payloadText = string(b)
	}
	if s.readModel != nil && sessionID != "" {
		_ = s.readModel.InsertEvent(
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
	subs := make([]chan OutboundEvent, 0)
	if byWorkflow, ok := s.subscribers[workflowID]; ok {
		for _, ch := range byWorkflow {
			subs = append(subs, ch)
		}
	}
	s.mu.Unlock()

	sseBody := map[string]any{
		"schema_version": 1,
		"correlation_id": correlationID,
		"event_id":       fmt.Sprintf("%d", eventID),
		"event_type":     eventType,
		"workflow_id":    workflowID,
		"run_id":         runID,
		"session_id":     sessionID,
		"seq":            seq,
		"occurred_at":    occurredAt,
		"stream_id":      ev.StreamID,
		"payload":        payloadMap,
	}
	buf, _ := json.Marshal(sseBody)
	for _, ch := range subs {
		select {
		case ch <- OutboundEvent{ID: ev.ID, Event: eventType, Payload: buf}:
		default:
		}
	}
}

func correlationIDFromPayload(payload map[string]any, workflowID string, runID string) string {
	_ = workflowID
	_ = runID
	if payload != nil {
		if value, ok := payload["correlation_id"].(string); ok {
			trimmed := strings.TrimSpace(value)
			if trimmed != "" {
				return trimmed
			}
		}
		if nested, ok := payload["payload"].(map[string]any); ok && nested != nil {
			if value, ok := nested["correlation_id"].(string); ok {
				trimmed := strings.TrimSpace(value)
				if trimmed != "" {
					return trimmed
				}
			}
		}
	}
	return ""
}

func (s *Server) nextRunSeq(runID string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.runSeqByRunID == nil {
		s.runSeqByRunID = make(map[string]int64)
	}
	next := s.runSeqByRunID[runID] + 1
	s.runSeqByRunID[runID] = next
	return next
}

func (s *Server) workflowRunID(workflowID string) string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return strings.TrimSpace(s.workflowRunByWorkflowID[workflowID])
}

func (s *Server) resolveRunID(ctx context.Context, workflowID string, payload any) string {
	runID := runIDFromPayload(payload)
	if runID != "" {
		s.bindWorkflowRunID(workflowID, runID)
		return runID
	}
	runID = s.workflowRunID(workflowID)
	if runID != "" {
		return runID
	}
	if s.workflowSvc == nil || !s.workflowSvc.Enabled() {
		return ""
	}
	descCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	desc, err := s.workflowSvc.DescribeWorkflow(descCtx, workflowID, "")
	if err != nil || desc == nil {
		return ""
	}
	runID = strings.TrimSpace(desc.RunID)
	if runID != "" {
		s.bindWorkflowRunID(workflowID, runID)
	}
	return runID
}

func (s *Server) bindWorkflowRunID(workflowID, runID string) {
	if workflowID == "" || runID == "" {
		return
	}
	s.mu.Lock()
	if s.workflowRunByWorkflowID == nil {
		s.workflowRunByWorkflowID = make(map[string]string)
	}
	s.workflowRunByWorkflowID[workflowID] = runID
	s.mu.Unlock()
}

func runIDFromPayload(payload any) string {
	obj, ok := payload.(map[string]any)
	if !ok || obj == nil {
		return ""
	}
	if runID, ok := obj["run_id"].(string); ok {
		runID = strings.TrimSpace(runID)
		if runID != "" {
			return runID
		}
	}
	if nested, ok := obj["payload"].(map[string]any); ok && nested != nil {
		if runID, ok := nested["run_id"].(string); ok {
			runID = strings.TrimSpace(runID)
			if runID != "" {
				return runID
			}
		}
	}
	return ""
}

func (s *Server) subscribe(workflowID string) (int, chan OutboundEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.subscriberSeq++
	id := s.subscriberSeq
	if _, ok := s.subscribers[workflowID]; !ok {
		s.subscribers[workflowID] = make(map[int]chan OutboundEvent)
	}
	ch := make(chan OutboundEvent, 128)
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
	if s.streamSubscriber == nil {
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
		s.subscribeGoAgentStream(ctx, workflowID)
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

func (s *Server) subscribeGoAgentStream(ctx context.Context, workflowID string) {
	sessionID := workflowID
	if s.readModel != nil {
		if sid, err := s.readModel.GetTaskSession(ctx, workflowID); err == nil && sid != "" {
			sessionID = strings.TrimSpace(sid)
		}
	}

	sub, err := s.streamSubscriber.Subscribe(ctx, sessionID, 0)
	if err != nil {
		log.Printf("goagent stream subscribe failed workflow_id=%s session_id=%s err=%v", workflowID, sessionID, err)
		return
	}
	defer sub.Close()

	usageProjector := NewUsageProjector(
		func(ctx context.Context, row usecase.UsageLedgerRow) (bool, error) {
			if s.readModel == nil {
				return false, nil
			}
			return s.readModel.InsertLLMUsage(ctx, row)
		},
		log.Printf,
		func() { atomic.AddInt64(&s.llmUsageIngested, 1) },
		func() { atomic.AddInt64(&s.llmUsageDeduped, 1) },
		func() { atomic.AddInt64(&s.llmUsageFailed, 1) },
		func() { atomic.AddInt64(&s.llmUsageInvalid, 1) },
	)

	for {
		select {
		case <-ctx.Done():
			return
		case stored, ok := <-sub.C:
			if !ok {
				return
			}
			base := stored.Event.Base()
			runID := strings.TrimSpace(base.RunID)
			evSessionID := strings.TrimSpace(base.SessionID)
			eventType := base.EventType
			if eventType == "" {
				eventType = "WORKFLOW_PROGRESS"
			}
			if evSessionID == "" {
				evSessionID = sessionID
			}
			if runID != "" {
				s.bindWorkflowRunID(workflowID, runID)
			}

			payload := map[string]any{
				"event_type":  eventType,
				"workflow_id": workflowID,
				"run_id":      runID,
				"session_id":  evSessionID,
				"event_id":    strings.TrimSpace(base.EventID),
				"timestamp":   base.Timestamp,
				"sequence":    stored.Sequence,
			}

			normalized := NormalizedEvent{
				WorkflowID: workflowID,
				SessionID:  evSessionID,
				TaskID:     workflowID,
				EventType:  eventType,
				StreamID:   fmt.Sprintf("%d", stored.Sequence),
				Payload:    payload,
			}
			usageProjector.Project(ctx, normalized)

			s.appendTimelineWithStreamID(
				workflowID,
				evSessionID,
				eventType,
				"",
				normalized.StreamID,
				payload,
			)
		}
	}
}
