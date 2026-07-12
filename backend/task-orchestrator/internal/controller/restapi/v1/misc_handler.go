package v1

import (
	"net/http"
	"strings"
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
