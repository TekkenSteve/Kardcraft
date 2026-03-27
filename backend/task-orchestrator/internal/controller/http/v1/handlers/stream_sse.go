package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	v1stream "task-orchestrator/internal/controller/http/v1/stream"
)

type SSEDeps struct {
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	UserID        func(r *http.Request) string
	Authorize     func(r *http.Request, userID, workflowID string) bool
	NowRFC3339    func() string

	Subscribe                  func(workflowID string) (int, chan v1stream.OutboundEvent)
	Unsubscribe                func(workflowID string, subscriberID int)
	EnsureWorkflowStreamReader func(workflowID string)
	Backlog                    func(workflowID string) []map[string]any

	AuthzDeniedCode string
}

func NewSSEHandler(deps SSEDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		workflowID := strings.TrimSpace(r.URL.Query().Get("workflow_id"))
		if workflowID == "" {
			http.Error(w, "workflow_id required", http.StatusBadRequest)
			return
		}
		userID := deps.UserID(r)
		if !deps.Authorize(r, userID, workflowID) {
			deps.WriteAPIError(w, http.StatusForbidden, deps.AuthzDeniedCode, "access denied for workflow stream", map[string]any{
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

		subscriberID, events := deps.Subscribe(workflowID)
		defer deps.Unsubscribe(workflowID, subscriberID)
		deps.EnsureWorkflowStreamReader(workflowID)

		fmt.Fprintf(w, ": %s\n\n", strings.Repeat(" ", 1024))
		initEvent := map[string]any{
			"type":        "STATUS_UPDATE",
			"workflow_id": workflowID,
			"message":     "Stream connected",
			"timestamp":   deps.NowRFC3339(),
		}
		buf, _ := json.Marshal(initEvent)
		fmt.Fprintf(w, "event: STATUS_UPDATE\ndata: %s\n\n", string(buf))
		flusher.Flush()

		for _, payload := range deps.Backlog(workflowID) {
			eventType, _ := payload["type"].(string)
			if strings.TrimSpace(eventType) == "" {
				eventType = "STATUS_UPDATE"
			}
			b, _ := json.Marshal(payload)
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", eventType, string(b))
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
				fmt.Fprintf(w, ": ping %d\n\n", time.Now().UTC().Unix())
				flusher.Flush()
			case ev, ok := <-events:
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
