package v1

import (
	"fmt"
	"net/http"
	"sync/atomic"
)

func (s *Server) registerTaskRoutes() {
	tasksDeps := TasksDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		NowRFC3339:    nowRFC3339,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		TaskService:                s.taskService,
		CommandService:             s.commandService,
		ReadModel:                  s.readModel,
		AgentRuntime:               s.agentRuntime,
		DefaultModelRef:            s.defaultModelRef,
		IsAgentRuntimeAvailable:    s.isAgentRuntimeAvailable,
		NextWorkflowID:             s.nextWorkflowID,
		EnsureWorkflowStreamReader: s.ensureWorkflowStreamReader,
		AppendTimelineWithStreamID: s.appendTimelineWithStreamID,
		BindWorkflowRunID:          s.bindWorkflowRunID,
		AuthorizeTaskAccess: func(r *http.Request, userID, taskID string) bool {
			return s.authorizeTaskAccess(r.Context(), userID, taskID)
		},
		ActiveTaskCode:          errCodeActiveTaskExists,
		AuthzDeniedCode:         errCodeAuthzDenied,
		IdempotencyRequiredCode: errCodeIdempotencyKeyRequired,
	}
	s.mux.HandleFunc("/api/v1/tasks", NewTasksHandler(tasksDeps))
	s.mux.HandleFunc("/api/v1/tasks/template", NewTemplateTasksHandler(tasksDeps))
	s.mux.HandleFunc("/api/v1/tasks/", NewTaskDetailRouter(tasksDeps))

	s.mux.HandleFunc("/api/v1/agentos/runs/", NewAgentOSEventsHandler(AgentOSEventsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		ReadModel:     s.readModel,
		OutcomeStore:  s.sessionStore,
		AppendTimeline: func(workflowID, sessionID, eventType, message, streamID string, payload any, persist bool) {
			if persist {
				s.appendTimelineWithStreamID(workflowID, sessionID, eventType, message, streamID, payload)
				return
			}
			s.appendTimelineTransient(workflowID, sessionID, eventType, message, streamID, payload)
		},
	}))

	s.mux.HandleFunc("/api/v1/stream/sse", NewSSEHandler(SSEDeps{
		WriteAPIError: writeAPIError,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		Authorize: func(r *http.Request, userID, workflowID string) bool {
			return s.authorizeTaskAccess(r.Context(), userID, workflowID)
		},
		NowRFC3339: nowRFC3339,
		Subscribe:  s.subscribe,
		Unsubscribe: func(workflowID string, subscriberID int) {
			s.unsubscribe(workflowID, subscriberID)
		},
		EnsureWorkflowStreamReader: s.ensureWorkflowStreamReader,
		Backlog: func(workflowID string, afterEventID int64) []map[string]any {
			s.mu.RLock()
			backlog := append([]TimelineEvent(nil), s.timelineByWorkflow[workflowID]...)
			s.mu.RUnlock()
			out := make([]map[string]any, 0, len(backlog))
			for _, ev := range backlog {
				if afterEventID > 0 && ev.ID <= afterEventID {
					continue
				}
				correlationID := correlationIDFromPayload(anyToMap(ev.Payload), ev.WorkflowID, ev.RunID)
				if correlationID == "" {
					continue
				}
				payload := map[string]any{
					"schema_version": 1,
					"correlation_id": correlationID,
					"event_id":       fmt.Sprintf("%d", ev.ID),
					"event_type":     ev.Type,
					"workflow_id":    ev.WorkflowID,
					"run_id":         ev.RunID,
					"session_id":     ev.SessionID,
					"seq":            ev.Seq,
					"occurred_at":    ev.Timestamp,
					"stream_id":      ev.StreamID,
					"payload":        ev.Payload,
				}
				out = append(out, payload)
			}
			return out
		},
		AuthzDeniedCode: errCodeAuthzDenied,
	}))
}

func anyToMap(input any) map[string]any {
	typed, ok := input.(map[string]any)
	if !ok || typed == nil {
		return map[string]any{}
	}
	return typed
}

func (s *Server) registerSessionAndTemplateRoutes() {
	sessionsDeps := SessionsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		ReadModel:               s.readModel,
		CommandService:          s.commandService,
		IsAgentRuntimeAvailable: s.isAgentRuntimeAvailable,
		ActiveTaskCode:          errCodeActiveTaskExists,
		AuthzDeniedCode:         errCodeAuthzDenied,
	}
	s.mux.HandleFunc("/api/v1/sessions", NewSessionsHandler(sessionsDeps))
	s.mux.HandleFunc("/api/v1/sessions/", NewSessionsRouter(sessionsDeps))

	templatesDeps := TemplatesDeps{
		WriteJSON:    writeJSON,
		WriteRawJSON: writeRawJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		NowRFC3339:     nowRFC3339,
		HTTPClient:     s.httpClient,
		AnkiRuntimeURL: s.ankiRuntimeURL,
		ReadModel:      s.readModel,
	}
	s.mux.HandleFunc("/api/v1/card-templates", NewCardTemplatesHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/preview", NewCardTemplatePreviewHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/validate", NewCardTemplateValidateHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/required-fields", NewCardTemplateRequiredFieldsHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/precheck", NewCardTemplatePrecheckHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/build-apkg", NewCardTemplateBuildApkgHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/", NewCardTemplateDetailHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/users/me/template-preferences", NewUserTemplatePreferencesHandler(templatesDeps))

	s.mux.HandleFunc("/api/v1/schedules", NewSchedulesHandler(SchedulesDeps{WriteJSON: writeJSON}))
	s.mux.HandleFunc("/api/v1/schedules/", NewScheduleDetailHandler())

	s.mux.HandleFunc("/api/v1/cards/", NewCardsHandler(CardsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		ReadModel: s.readModel,
	}))

	exportsDeps := ExportsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		NowRFC3339:     nowRFC3339,
		HTTPClient:     s.httpClient,
		AnkiRuntimeURL: s.ankiRuntimeURL,
		ReadModel:      s.readModel,
	}
	s.mux.HandleFunc("/api/v1/exports/apkg", NewApkgExportsHandler(exportsDeps))
	s.mux.HandleFunc("/api/v1/exports/apkg/", NewApkgExportDetailRouter(exportsDeps))
}

func (s *Server) registerMiscRoutes() {
	health := NewHealthHandler(HealthDeps{
		WriteJSON: writeJSON,
		Port:      s.port,
		StreamReaders: func() int {
			s.mu.RLock()
			defer s.mu.RUnlock()
			return len(s.streamReaders)
		},
		DuplicateDrops: func() int64 { return atomic.LoadInt64(&s.duplicateDrops) },
		UsageIngested:  func() int64 { return atomic.LoadInt64(&s.llmUsageIngested) },
		UsageDeduped:   func() int64 { return atomic.LoadInt64(&s.llmUsageDeduped) },
		UsageFailed:    func() int64 { return atomic.LoadInt64(&s.llmUsageFailed) },
		UsageInvalid:   func() int64 { return atomic.LoadInt64(&s.llmUsageInvalid) },
	})
	s.mux.HandleFunc("/health", health)
	s.mux.HandleFunc("/health/task-orchestrator", health)
	s.mux.HandleFunc("/", NewRootHandler(RootDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
		Port:       s.port,
	}))
}
