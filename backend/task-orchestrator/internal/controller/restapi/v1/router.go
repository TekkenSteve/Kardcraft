package v1

import (
	"net/http"
)

func (s *Server) registerTaskRoutes() {
	tasksDeps := TasksDeps{
		WriteJSON:     writeJSON,
		WriteAPIError: writeAPIError,
		NowRFC3339:    nowRFC3339,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		TaskService:              s.taskService,
		CommandService:           s.commandService,
		ReadModel:                s.readModel,
		TemplateService:          s.templateService,
		TaskPreparation:          s.taskPreparation,
		Workspace:                s.workspaceService,
		TaskExecution:            s.taskExecution,
		DefaultModelRef:          s.defaultModelRef,
		IsTaskExecutionAvailable: s.isTaskExecutionAvailable,
		NextWorkflowID:           s.nextWorkflowID,
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
	if s.internalExecutionEvents != nil {
		s.mux.Handle("/internal/execution/runs/", s.internalExecutionEvents)
	}

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
		ReadModel:                s.readModel,
		Workspace:                s.workspaceService,
		CommandService:           s.commandService,
		Conversation:             s.conversation,
		IsTaskExecutionAvailable: s.isTaskExecutionAvailable,
		ActiveTaskCode:           errCodeActiveTaskExists,
		AuthzDeniedCode:          errCodeAuthzDenied,
	}
	s.mux.HandleFunc("/api/v1/sessions", NewSessionsHandler(sessionsDeps))
	s.mux.HandleFunc("/api/v1/sessions/", NewSessionsRouter(sessionsDeps))

	templatesDeps := TemplatesDeps{
		WriteJSON:    writeJSON,
		WriteRawJSON: writeRawJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		NowRFC3339: nowRFC3339,
		Service:    s.templateService,
	}
	s.mux.HandleFunc("/api/v1/card-templates", NewCardTemplatesHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/preview", NewCardTemplatePreviewHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/validate", NewCardTemplateValidateHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/required-fields", NewCardTemplateRequiredFieldsHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/precheck", NewCardTemplatePrecheckHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/build-apkg", NewCardTemplateBuildApkgHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/card-templates/", NewCardTemplateDetailHandler(templatesDeps))
	s.mux.HandleFunc("/api/v1/users/me/template-preferences", NewUserTemplatePreferencesHandler(templatesDeps))

	s.mux.HandleFunc("/api/v1/schedules", NewSchedulesHandler(SchedulesDeps{WriteJSON: writeJSON, UserID: func(r *http.Request) string { return userIDFromContext(r.Context()) }, Service: s.scheduleService}))
	s.mux.HandleFunc("/api/v1/schedules/", NewScheduleDetailHandler(SchedulesDeps{WriteJSON: writeJSON, UserID: func(r *http.Request) string { return userIDFromContext(r.Context()) }, Service: s.scheduleService}))

	s.mux.HandleFunc("/api/v1/cards/", NewCardsHandler(CardsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		Workspace: s.workspaceService,
	}))

	exportsDeps := ExportsDeps{
		WriteJSON: writeJSON,
		UserID: func(r *http.Request) string {
			return userIDFromContext(r.Context())
		},
		ReadModel: s.readModel,
		Service:   s.apkgExportService,
	}
	s.mux.HandleFunc("/api/v1/exports/apkg", NewApkgExportsHandler(exportsDeps))
	s.mux.HandleFunc("/api/v1/exports/apkg/", NewApkgExportDetailRouter(exportsDeps))
}

func (s *Server) registerMiscRoutes() {
	health := NewHealthHandler(HealthDeps{
		WriteJSON:      writeJSON,
		Port:           s.port,
		StreamReaders:  func() int { return 0 },
		DuplicateDrops: func() int64 { return 0 },
		UsageIngested:  func() int64 { return 0 },
		UsageDeduped:   func() int64 { return 0 },
		UsageFailed:    func() int64 { return 0 },
		UsageInvalid:   func() int64 { return 0 },
	})
	s.mux.HandleFunc("/health", health)
	s.mux.HandleFunc("/health/task-orchestrator", health)
	s.mux.HandleFunc("/", NewRootHandler(RootDeps{
		WriteJSON:  writeJSON,
		NowRFC3339: nowRFC3339,
		Port:       s.port,
	}))
}
