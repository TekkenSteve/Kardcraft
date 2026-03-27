package httpserver

import (
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	v1handlers "task-orchestrator/internal/controller/http/v1/handlers"
)

func (s *Server) registerTaskRoutes() {
	tasksDeps := v1handlers.TasksDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		NowRFC3339:    nowRFC3339,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		TaskService:                s.taskService,
		CommandService:             s.commandService,
		ReadModel:                  s.readModel,
		WorkflowSvc:                s.workflowSvc,
		IsTemporalEnabled:          s.isTemporalEnabled,
		NextWorkflowID:             s.nextWorkflowID,
		EnsureWorkflowStreamReader: s.ensureWorkflowStreamReader,
		AuthorizeTaskAccess: func(r *http.Request, userID, taskID string) bool {
			return s.authorizeTaskAccess(r.Context(), userID, taskID)
		},
		ActiveTaskCode:  errCodeActiveTaskExists,
		AuthzDeniedCode: errCodeAuthzDenied,
	}
	s.mux.HandleFunc("/api/v1/tasks", v1handlers.NewTasksHandler(tasksDeps))
	s.mux.HandleFunc("/api/v1/tasks/template", v1handlers.NewTemplateTasksHandler(tasksDeps))
	s.mux.HandleFunc("/api/v1/tasks/", v1handlers.NewTaskDetailRouter(tasksDeps))

	s.mux.HandleFunc("/api/v1/events", v1handlers.NewEventsHandler(v1handlers.EventsDeps{
		WriteJSON: writeJSON,
		ResolveSession: func(r *http.Request, workflowID string) string {
			taskObj, _ := s.taskService.GetTask(r.Context(), workflowID)
			if taskObj != nil {
				return taskObj.SessionID()
			}
			if s.readModel != nil {
				if sid, err := s.readModel.GetTaskSession(r.Context(), workflowID); err == nil {
					return sid
				}
			}
			return ""
		},
		AppendTimeline: s.appendTimeline,
	}))

	s.mux.HandleFunc("/api/v1/stream/sse", v1handlers.NewSSEHandler(v1handlers.SSEDeps{
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
		Backlog: func(workflowID string) []map[string]any {
			s.mu.RLock()
			backlog := append([]TimelineEvent(nil), s.timelineByWorkflow[workflowID]...)
			s.mu.RUnlock()
			out := make([]map[string]any, 0, len(backlog))
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
				out = append(out, payload)
			}
			return out
		},
		AuthzDeniedCode: errCodeAuthzDenied,
	}))
}

func (s *Server) registerSessionAndTemplateRoutes() {
	sessionsDeps := v1handlers.SessionsDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		ReadModel:               s.readModel,
		WorkflowSvc:             s.workflowSvc,
		CommandService:          s.commandService,
		IsTemporalEnabled:       s.isTemporalEnabled,
		AuthzDeniedCode:         errCodeAuthzDenied,
		IdempotencyRequiredCode: errCodeIdempotencyKeyRequired,
		NoActiveTaskCode:        errCodeNoActiveTask,
		InvalidTransitionCode:   errCodeInvalidTransition,
	}
	s.mux.HandleFunc("/api/v1/sessions", v1handlers.NewSessionsHandler(sessionsDeps))
	s.mux.HandleFunc("/api/v1/sessions/", v1handlers.NewSessionsRouter(sessionsDeps))

	templatesDeps := v1handlers.TemplatesDeps{
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
	s.mux.HandleFunc("/api/v1/card-templates", v1handlers.NewCardTemplatesHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/preview", v1handlers.NewCardTemplatePreviewHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/validate", v1handlers.NewCardTemplateValidateHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/required-fields", v1handlers.NewCardTemplateRequiredFieldsHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/precheck", v1handlers.NewCardTemplatePrecheckHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/build-apkg", v1handlers.NewCardTemplateBuildApkgHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/", v1handlers.NewCardTemplateDetailHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/users/me/template-preferences", v1handlers.NewUserTemplatePreferencesHandler(templatesDeps))

	s.mux.HandleFunc("/api/v1/schedules", v1handlers.NewSchedulesHandler(v1handlers.SchedulesDeps{WriteJSON: writeJSON}))
	s.mux.HandleFunc("/api/v1/schedules/", v1handlers.NewScheduleDetailHandler())

	s.mux.HandleFunc("/api/v1/cards/", v1handlers.NewCardsHandler(v1handlers.CardsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		ReadModel: s.readModel,
	}))

	exportsDeps := v1handlers.ExportsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		NowRFC3339:     nowRFC3339,
		HTTPClient:     s.httpClient,
		AnkiRuntimeURL: s.ankiRuntimeURL,
		ReadModel:      s.readModel,
	}
	s.mux.HandleFunc("/api/v1/exports/apkg", v1handlers.NewApkgExportsHandler(exportsDeps))
	s.mux.HandleFunc("/api/v1/exports/apkg/", v1handlers.NewApkgExportDetailRouter(exportsDeps))
}

func (s *Server) registerWorkflowRoutes() {
	workflowDeps := v1handlers.WorkflowsDeps{
		WriteJSON: writeJSON,
		WriteAPIError: func(w http.ResponseWriter, status int, code, message string, details map[string]any) {
			writeAPIError(w, status, code, message, details)
		},
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		Authorize: func(r *http.Request, userID, workflowID string) bool {
			return s.authorizeTaskAccess(r.Context(), userID, workflowID)
		},
		Status: func(r *http.Request, workflowID, runID string) (map[string]any, error) {
			if s.workflowSvc == nil || !s.workflowSvc.Enabled() {
				return nil, fmt.Errorf("temporal not enabled")
			}
			describeResp, err := s.workflowSvc.DescribeWorkflow(r.Context(), workflowID, runID)
			if err != nil {
				return nil, fmt.Errorf("failed to get workflow status: %w", err)
			}
			closeTime := ""
			if describeResp.CloseTime != nil {
				closeTime = describeResp.CloseTime.UTC().Format(time.RFC3339)
			}
			return map[string]any{
				"workflow_id": workflowID,
				"run_id":      describeResp.RunID,
				"status":      strings.ToLower(strings.TrimPrefix(describeResp.Status, "TASK_STATUS_")),
				"start_time":  describeResp.StartTime.UTC().Format(time.RFC3339),
				"close_time":  closeTime,
			}, nil
		},
		Cancel: func(r *http.Request, workflowID, reason string) error {
			if s.workflowSvc == nil || !s.workflowSvc.Enabled() {
				return fmt.Errorf("temporal not enabled")
			}
			return s.workflowSvc.CancelWorkflow(r.Context(), workflowID, reason)
		},
		History: func(r *http.Request, workflowID string) ([]map[string]any, error) {
			if s.workflowSvc == nil {
				return nil, fmt.Errorf("workflow service unavailable")
			}
			events, err := s.workflowSvc.ListHistory(r.Context(), workflowID)
			if err != nil {
				return nil, fmt.Errorf("failed to load workflow events: %w", err)
			}
			out := make([]map[string]any, 0, len(events))
			for _, ev := range events {
				out = append(out, map[string]any{
					"event_id":   ev.EventID,
					"event_type": ev.EventType,
					"timestamp":  ev.Timestamp.UTC().Format(time.RFC3339),
				})
			}
			return out, nil
		},
	}
	s.mux.HandleFunc("/api/v1/workflows/status", v1handlers.NewWorkflowStatusHandler(workflowDeps))
	s.mux.HandleFunc("/api/v1/workflows/cancel", v1handlers.NewWorkflowCancelHandler(workflowDeps))
	s.mux.HandleFunc("/api/v1/workflows/history", v1handlers.NewWorkflowHistoryHandler(workflowDeps))
}

func (s *Server) registerUploadRoutes() {
	uploads := v1handlers.UploadsDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
		NewUploadID: func() string {
			return fmt.Sprintf("upload_%d", time.Now().UTC().UnixNano())
		},
		InitUpload: func(uploadID, fileName string, chunks int, sessionID string, createdAt string) {
			s.mu.Lock()
			s.uploads[uploadID] = &uploadState{
				UploadID:  uploadID,
				Status:    "initialized",
				FileName:  fileName,
				Chunks:    chunks,
				Received:  0,
				SessionID: sessionID,
				CreatedAt: createdAt,
			}
			s.mu.Unlock()
		},
		IncrementChunk: func(uploadID string) (int, bool) {
			s.mu.Lock()
			defer s.mu.Unlock()
			state, ok := s.uploads[uploadID]
			if ok {
				state.Received++
				state.Status = "uploading"
				return state.Received, true
			}
			return 0, false
		},
		CompleteUpload: func(uploadID string, completedAt string) bool {
			s.mu.Lock()
			defer s.mu.Unlock()
			state, ok := s.uploads[uploadID]
			if ok {
				state.Status = "completed"
				state.CompletedAt = completedAt
				return true
			}
			return false
		},
		GetUploadStatus: func(uploadID string) (map[string]any, bool) {
			s.mu.RLock()
			defer s.mu.RUnlock()
			state, ok := s.uploads[uploadID]
			if !ok {
				return nil, false
			}
			return map[string]any{
				"upload_id":    state.UploadID,
				"status":       state.Status,
				"file_name":    state.FileName,
				"chunks":       state.Chunks,
				"received":     state.Received,
				"session_id":   state.SessionID,
				"created_at":   state.CreatedAt,
				"completed_at": state.CompletedAt,
			}, true
		},
	}
	s.mux.HandleFunc("/api/v1/files/upload/init", v1handlers.NewInitUploadHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/chunk/", v1handlers.NewUploadChunkHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/complete/", v1handlers.NewCompleteUploadHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/status/", v1handlers.NewUploadStatusHandler(uploads))
}

func (s *Server) registerMiscRoutes() {
	s.mux.HandleFunc("/api/agents", v1handlers.NewAgentsHandler(v1handlers.AgentsDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
	}))
	health := v1handlers.NewHealthHandler(v1handlers.HealthDeps{
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
		UsageSchemaMis: func() int64 { return atomic.LoadInt64(&s.llmUsageSchemaMismatch) },
		RedisStats: func() map[string]any {
			if s.redisSvc == nil {
				return nil
			}
			return s.redisSvc.Stats()
		},
	})
	s.mux.HandleFunc("/health", health)
	s.mux.HandleFunc("/health/task-orchestrator", health)
	s.mux.HandleFunc("/", v1handlers.NewRootHandler(v1handlers.RootDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
		Port:       s.port,
	}))
}
