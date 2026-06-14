package v1

import (
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"time"
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
		WorkflowSvc:                s.workflowSvc,
		DefaultModelRef:            s.defaultModelRef,
		IsTemporalEnabled:          s.isTemporalEnabled,
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

	s.mux.HandleFunc("/api/v1/events", NewEventsHandler(EventsDeps{
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
		ReadModel:         s.readModel,
		WorkflowSvc:       s.workflowSvc,
		CommandService:    s.commandService,
		IsTemporalEnabled: s.isTemporalEnabled,
		AuthzDeniedCode:   errCodeAuthzDenied,
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

func (s *Server) registerWorkflowRoutes() {
	workflowDeps := WorkflowsDeps{
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
	s.mux.HandleFunc("/api/v1/workflows/status", NewWorkflowStatusHandler(workflowDeps))
	s.mux.HandleFunc("/api/v1/workflows/cancel", NewWorkflowCancelHandler(workflowDeps))
	s.mux.HandleFunc("/api/v1/workflows/history", NewWorkflowHistoryHandler(workflowDeps))
}

func (s *Server) registerUploadRoutes() {
	uploads := UploadsDeps{
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
	s.mux.HandleFunc("/api/v1/files/upload/init", NewInitUploadHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/chunk/", NewUploadChunkHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/complete/", NewCompleteUploadHandler(uploads))
	s.mux.HandleFunc("/api/v1/files/upload/status/", NewUploadStatusHandler(uploads))
}

func (s *Server) registerMiscRoutes() {
	s.mux.HandleFunc("/api/agents", NewAgentsHandler(AgentsDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
	}))
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
