package httpserver

import "net/http"

func (s *Server) schedulesHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method == http.MethodGet {
		writeJSON(w, http.StatusOK, map[string]any{"schedules": []any{}, "total_count": 0})
		return
	}
	http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
}

func (s *Server) scheduleDetailHandler(w http.ResponseWriter, r *http.Request) {
	http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
}

func (s *Server) handleScheduleRuns(w http.ResponseWriter, r *http.Request, scheduleID string) {
	http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
}

func (s *Server) handleSchedulePauseResume(w http.ResponseWriter, r *http.Request, scheduleID string, targetStatus string) {
	http.Error(w, "schedule persistence is not implemented", http.StatusNotImplemented)
}
