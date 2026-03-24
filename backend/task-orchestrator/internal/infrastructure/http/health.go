package httpserver

import (
	"net/http"
	"sync/atomic"
)

func (s *Server) healthHandler(w http.ResponseWriter, r *http.Request) {
	streamReaders := 0
	s.mu.RLock()
	streamReaders = len(s.streamReaders)
	s.mu.RUnlock()
	resp := map[string]any{
		"status":  "ok",
		"service": "task-orchestrator",
		"port":    s.port,
		"metrics": map[string]any{
			"stream_readers":         streamReaders,
			"stream_duplicate_drops": atomic.LoadInt64(&s.duplicateDrops),
			"llm_usage_ingested":     atomic.LoadInt64(&s.llmUsageIngested),
			"llm_usage_deduped":      atomic.LoadInt64(&s.llmUsageDeduped),
			"llm_usage_failed":       atomic.LoadInt64(&s.llmUsageFailed),
			"llm_usage_invalid":      atomic.LoadInt64(&s.llmUsageInvalid),
			"llm_usage_schema_miss":  atomic.LoadInt64(&s.llmUsageSchemaMismatch),
		},
	}
	if s.redisSvc != nil {
		resp["redis_stream"] = s.redisSvc.Stats()
	}
	writeJSON(w, http.StatusOK, resp)
}
