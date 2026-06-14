package v1

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

type HealthDeps struct {
	WriteJSON      func(w http.ResponseWriter, status int, v any)
	Port           int
	StreamReaders  func() int
	DuplicateDrops func() int64
	UsageIngested  func() int64
	UsageDeduped   func() int64
	UsageFailed    func() int64
	UsageInvalid   func() int64
}

func NewHealthHandler(deps HealthDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		resp := map[string]any{
			"status":  "ok",
			"service": "task-orchestrator",
			"port":    deps.Port,
			"metrics": map[string]any{
				"stream_readers":         deps.StreamReaders(),
				"stream_duplicate_drops": deps.DuplicateDrops(),
				"llm_usage_ingested":     deps.UsageIngested(),
				"llm_usage_deduped":      deps.UsageDeduped(),
				"llm_usage_failed":       deps.UsageFailed(),
				"llm_usage_invalid":      deps.UsageInvalid(),
			},
		}
		deps.WriteJSON(w, http.StatusOK, resp)
	}
}

type RootDeps struct {
	WriteJSON  func(w http.ResponseWriter, status int, v any)
	NowRFC3339 func() string
	Port       int
}

func NewRootHandler(deps RootDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			deps.WriteJSON(w, http.StatusNotFound, map[string]any{
				"error":  "API endpoint not found",
				"path":   r.URL.Path,
				"method": r.Method,
			})
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"service": "Task Orchestrator Service",
			"port":    deps.Port,
			"time":    deps.NowRFC3339(),
			"status":  "running",
		})
	}
}

type AgentsDeps struct {
	WriteJSON  func(w http.ResponseWriter, status int, v any)
	NowRFC3339 func() string
}

func NewAgentsHandler(deps AgentsDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			deps.WriteJSON(w, http.StatusOK, map[string]any{
				"agent_id":   fmt.Sprintf("agent_%d", time.Now().UTC().Unix()),
				"name":       "test-agent",
				"status":     "AGENT_STATUS_ACTIVE",
				"message":    "Agent created successfully",
				"created_at": deps.NowRFC3339(),
			})
			return
		}
		deps.WriteJSON(w, http.StatusOK, map[string]any{
			"agents":      []any{},
			"total_count": 0,
			"message":     "Agent service is running",
		})
	}
}

type SchedulesDeps struct {
	WriteJSON func(w http.ResponseWriter, status int, v any)
}

func NewSchedulesHandler(deps SchedulesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Method == http.MethodGet {
			deps.WriteJSON(w, http.StatusOK, map[string]any{"schedules": []any{}, "total_count": 0})
			return
		}
		http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
	}
}

func NewScheduleDetailHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
	}
}
