package v1

import (
	"net/http"
	"strings"

	"task-orchestrator/internal/usecase"
)

type TasksDeps struct {
	WriteJSON     func(w http.ResponseWriter, status int, v any)
	WriteAPIError func(w http.ResponseWriter, status int, code, message string, details map[string]any)
	NowRFC3339    func() string
	UserID        func(r *http.Request) string

	TaskService     usecase.Task
	CommandService  usecase.Command
	ReadModel       usecase.ReadModel
	TemplateService usecase.TemplateOperations
	TaskPreparation usecase.TaskInputPreparation
	Workspace       usecase.Workspace
	TaskExecution   usecase.TaskExecution
	DefaultModelRef string

	IsTaskExecutionAvailable func() bool
	NextWorkflowID           func(taskType string) string
	AuthorizeTaskAccess      func(r *http.Request, userID, taskID string) bool

	ActiveTaskCode          string
	AuthzDeniedCode         string
	IdempotencyRequiredCode string
}

func NewTasksHandler(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			handleListTasks(w, r, deps)
		case http.MethodPost:
			handleCreateTask(w, r, deps)
		case http.MethodOptions:
			w.WriteHeader(http.StatusOK)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func NewTaskDetailRouter(deps TasksDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		path := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/tasks/"), "/")
		if path == "" {
			http.NotFound(w, r)
			return
		}
		parts := strings.Split(path, "/")
		if len(parts) == 1 {
			if r.Method == http.MethodGet {
				handleGetTask(w, r, parts[0], deps)
				return
			}
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if len(parts) == 2 {
			handleTaskControl(w, r, parts[0], parts[1], deps)
			return
		}
		http.NotFound(w, r)
	}
}
