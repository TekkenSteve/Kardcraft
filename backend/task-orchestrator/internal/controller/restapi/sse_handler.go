package restapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"
)

type SSEDeps struct {
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string
	Authorize     func(r *http.Request, userID, workflowID string) bool
	NowRFC3339    func() string

	Subscribe                  func(workflowID string) (int, chan OutboundEvent)
	Unsubscribe                func(workflowID string, subscriberID int)
	EnsureWorkflowStreamReader func(workflowID string)
	Backlog                    func(workflowID string, afterEventID int64) []map[string]any

	AuthzDeniedCode string
}

func NewSSEHandler(deps SSEDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		workflowIDs := resolveWorkflowIDs(r)
		if len(workflowIDs) == 0 {
			http.Error(w, "workflow_id required", http.StatusBadRequest)
			return
		}
		afterEventID, hasCursor := resolveLastEventID(r)
		userID := deps.UserID(r)
		for _, workflowID := range workflowIDs {
			if !deps.Authorize(r, userID, workflowID) {
				deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for workflow stream", map[string]any{
					"workflow_id": workflowID,
				})
				return
			}
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

		type subscription struct {
			workflowID string
			id         int
			events     chan OutboundEvent
		}
		subscriptions := make([]subscription, 0, len(workflowIDs))
		for _, workflowID := range workflowIDs {
			subscriberID, events := deps.Subscribe(workflowID)
			subscriptions = append(subscriptions, subscription{
				workflowID: workflowID,
				id:         subscriberID,
				events:     events,
			})
			deps.EnsureWorkflowStreamReader(workflowID)
		}
		defer func() {
			for _, sub := range subscriptions {
				deps.Unsubscribe(sub.workflowID, sub.id)
			}
		}()

		fmt.Fprintf(w, ": %s\n\n", strings.Repeat(" ", 1024))
		flusher.Flush()

		if hasCursor {
			type backlogEvent struct {
				id      int64
				event   string
				payload map[string]any
			}
			events := make([]backlogEvent, 0, 128)
			for _, workflowID := range workflowIDs {
				for _, payload := range deps.Backlog(workflowID, afterEventID) {
					eventType, _ := payload["event_type"].(string)
					if strings.TrimSpace(eventType) == "" {
						eventType = "STATUS_UPDATE"
					}
					eventID := resolveBacklogEventID(payload)
					events = append(events, backlogEvent{
						id:      eventID,
						event:   eventType,
						payload: payload,
					})
				}
			}
			slices.SortFunc(events, func(a, b backlogEvent) int {
				if a.id < b.id {
					return -1
				}
				if a.id > b.id {
					return 1
				}
				return 0
			})
			for _, event := range events {
				if event.id > 0 {
					fmt.Fprintf(w, "id: %d\n", event.id)
				}
				b, _ := json.Marshal(event.payload)
				fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event.event, string(b))
			}
		}
		flusher.Flush()

		ctx := r.Context()
		merged := make(chan OutboundEvent, 256)
		mergeCtx, mergeCancel := context.WithCancel(ctx)
		var wg sync.WaitGroup
		for _, sub := range subscriptions {
			wg.Add(1)
			go func(ch chan OutboundEvent) {
				defer wg.Done()
				for {
					select {
					case <-mergeCtx.Done():
						return
					case ev, ok := <-ch:
						if !ok {
							return
						}
						select {
						case merged <- ev:
						case <-mergeCtx.Done():
							return
						}
					}
				}
			}(sub.events)
		}
		go func() {
			wg.Wait()
			close(merged)
		}()
		defer mergeCancel()

		heartbeat := time.NewTicker(10 * time.Second)
		defer heartbeat.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-heartbeat.C:
				fmt.Fprintf(w, ": ping %d\n\n", time.Now().UTC().Unix())
				flusher.Flush()
			case ev, ok := <-merged:
				if !ok {
					return
				}
				fmt.Fprintf(w, "id: %d\n", ev.ID)
				fmt.Fprintf(w, "event: %s\n", ev.Event)
				fmt.Fprintf(w, "data: %s\n\n", string(ev.Payload))
				flusher.Flush()
			}
		}
	}
}

func resolveWorkflowIDs(r *http.Request) []string {
	values := r.URL.Query()["workflow_id"]
	if len(values) == 0 {
		return nil
	}
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, raw := range values {
		for _, token := range strings.Split(raw, ",") {
			workflowID := strings.TrimSpace(token)
			if workflowID == "" {
				continue
			}
			if _, ok := seen[workflowID]; ok {
				continue
			}
			seen[workflowID] = struct{}{}
			out = append(out, workflowID)
		}
	}
	return out
}

func resolveBacklogEventID(payload map[string]any) int64 {
	if payload == nil {
		return 0
	}
	switch typed := payload["event_id"].(type) {
	case int64:
		if typed > 0 {
			return typed
		}
	case int:
		if typed > 0 {
			return int64(typed)
		}
	case float64:
		if typed > 0 {
			return int64(typed)
		}
	case string:
		return parseLastEventID(strings.TrimSpace(typed))
	}
	return 0
}

func resolveLastEventID(r *http.Request) (int64, bool) {
	queryValue := strings.TrimSpace(r.URL.Query().Get("last_event_id"))
	if queryValue != "" {
		return parseLastEventID(queryValue), true
	}
	headerValue := strings.TrimSpace(r.Header.Get("Last-Event-ID"))
	if headerValue != "" {
		return parseLastEventID(headerValue), true
	}
	return 0, false
}

func parseLastEventID(value string) int64 {
	if value == "" {
		return 0
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed < 0 {
		return 0
	}
	return parsed
}
