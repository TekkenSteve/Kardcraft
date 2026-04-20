package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync/atomic"
	"time"

	v1stream "task-orchestrator/internal/controller/http/v1/stream"
	"task-orchestrator/internal/usecase"
)

var timelineBroadcaster = v1stream.NewBroadcaster()

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
	subs := make([]chan v1stream.OutboundEvent, 0)
	if byWorkflow, ok := s.subscribers[workflowID]; ok {
		for _, ch := range byWorkflow {
			subs = append(subs, ch)
		}
	}
	s.mu.Unlock()

	var typedPayload map[string]any
	if payload != nil {
		if m, ok := payload.(map[string]any); ok {
			typedPayload = m
		}
	}
	buf, _ := timelineBroadcaster.BuildEventPayload(eventType, workflowID, workflowID, message, ev.Timestamp, ev.StreamID, typedPayload)
	for _, ch := range subs {
		select {
		case ch <- v1stream.OutboundEvent{ID: ev.ID, Event: eventType, Payload: buf}:
		default:
		}
	}
}

func (s *Server) subscribe(workflowID string) (int, chan v1stream.OutboundEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.subscriberSeq++
	id := s.subscriberSeq
	if _, ok := s.subscribers[workflowID]; !ok {
		s.subscribers[workflowID] = make(map[int]chan v1stream.OutboundEvent)
	}
	ch := make(chan v1stream.OutboundEvent, 128)
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

func (s *Server) subscribeRedisStream(ctx context.Context, workflowID string) {
	reader := v1stream.NewReader(s.redisSvc, 32, 5*time.Second, log.Printf)
	if !reader.Enabled() {
		return
	}

	normalizer := v1stream.NewNormalizer(func(ctx context.Context, taskID string) (string, error) {
		if s.readModel == nil {
			return "", nil
		}
		return s.readModel.GetTaskSession(ctx, taskID)
	})
	usageProjector := v1stream.NewUsageProjector(
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

	lastID := reader.StartFrom(ctx, workflowID)
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		entries, nextID, err := reader.Read(ctx, workflowID, lastID)
		if err != nil {
			return
		}
		lastID = nextID
		for _, msg := range entries {
			normalized := normalizer.Normalize(ctx, workflowID, msg)
			usageProjector.Project(ctx, normalized)
			s.appendTimelineWithStreamID(
				normalized.WorkflowID,
				normalized.SessionID,
				normalized.EventType,
				normalized.Message,
				normalized.StreamID,
				normalized.Payload,
			)
		}
		reader.SaveCheckpoint(ctx, workflowID, strings.TrimSpace(lastID))
	}
}
