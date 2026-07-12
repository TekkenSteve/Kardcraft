package v1

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"task-orchestrator/internal/usecase"
	"task-orchestrator/internal/usecase/schedule"
)

type ScheduleService interface {
	Create(context.Context, schedule.CreateInput) (*usecase.ScheduleRecord, error)
	Update(context.Context, schedule.UpdateInput) (*usecase.ScheduleRecord, error)
	Pause(context.Context, string, string, string) (*usecase.ScheduleRecord, error)
	Resume(context.Context, string, string, string) (*usecase.ScheduleRecord, error)
	Delete(context.Context, string, string) error
	Get(context.Context, string, string) (*usecase.ScheduleRecord, error)
	List(context.Context, string, int, int, string) ([]usecase.ScheduleRecord, int, error)
	Runs(context.Context, string, string, int, int) ([]usecase.ScheduleRunRow, int, error)
}

type SchedulesDeps struct {
	WriteJSON func(w http.ResponseWriter, status int, v any)
	UserID    func(*http.Request) string
	Service   ScheduleService
}

type scheduleRequest struct {
	Name           string `json:"name"`
	Description    string `json:"description"`
	CronExpression string `json:"cron_expression"`
	Timezone       string `json:"timezone"`
	TaskQuery      string `json:"task_query"`
}

type scheduleUpdateRequest struct {
	Name           *string `json:"name"`
	Description    *string `json:"description"`
	CronExpression *string `json:"cron_expression"`
	Timezone       *string `json:"timezone"`
	TaskQuery      *string `json:"task_query"`
}

func NewSchedulesHandler(deps SchedulesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		if deps.Service == nil {
			http.Error(w, "schedule service unavailable", http.StatusServiceUnavailable)
			return
		}

		switch r.Method {
		case http.MethodGet:
			limit, offset := schedulePagination(r)
			rows, total, err := deps.Service.List(r.Context(), deps.UserID(r), limit, offset, strings.ToLower(strings.TrimSpace(r.URL.Query().Get("status"))))
			if err != nil {
				writeScheduleError(w, deps, err)
				return
			}
			items := make([]map[string]any, 0, len(rows))
			for _, row := range rows {
				items = append(items, scheduleResponse(row))
			}
			deps.WriteJSON(w, http.StatusOK, map[string]any{"schedules": items, "total_count": total})
		case http.MethodPost:
			var request scheduleRequest
			if err := decodeScheduleRequest(r, &request); err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			row, err := deps.Service.Create(r.Context(), schedule.CreateInput{
				UserID:         deps.UserID(r),
				Name:           request.Name,
				Description:    request.Description,
				CronExpression: request.CronExpression,
				Timezone:       request.Timezone,
				TaskQuery:      request.TaskQuery,
			})
			if err != nil {
				writeScheduleError(w, deps, err)
				return
			}
			deps.WriteJSON(w, http.StatusCreated, scheduleResponse(*row))
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func NewScheduleDetailHandler(deps SchedulesDeps) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if deps.Service == nil {
			http.Error(w, "schedule service unavailable", http.StatusServiceUnavailable)
			return
		}
		parts := strings.Split(strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/schedules/"), "/"), "/")
		if len(parts) == 0 || parts[0] == "" {
			http.NotFound(w, r)
			return
		}
		if len(parts) == 1 {
			handleScheduleResource(w, r, deps, parts[0])
			return
		}
		if len(parts) != 2 {
			http.NotFound(w, r)
			return
		}
		switch parts[1] {
		case "runs":
			handleScheduleRuns(w, r, deps, parts[0])
		case "pause", "resume":
			handleScheduleStateChange(w, r, deps, parts[0], parts[1])
		default:
			http.NotFound(w, r)
		}
	}
}

func handleScheduleResource(w http.ResponseWriter, r *http.Request, deps SchedulesDeps, scheduleID string) {
	userID := deps.UserID(r)
	switch r.Method {
	case http.MethodGet:
		row, err := deps.Service.Get(r.Context(), scheduleID, userID)
		if err != nil {
			writeScheduleError(w, deps, err)
			return
		}
		deps.WriteJSON(w, http.StatusOK, scheduleResponse(*row))
	case http.MethodPut:
		var request scheduleUpdateRequest
		if err := decodeScheduleRequest(r, &request); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if request.Name == nil && request.Description == nil && request.CronExpression == nil && request.Timezone == nil && request.TaskQuery == nil {
			http.Error(w, "at least one schedule field is required", http.StatusBadRequest)
			return
		}
		row, err := deps.Service.Update(r.Context(), schedule.UpdateInput{
			ScheduleID:     scheduleID,
			UserID:         userID,
			Name:           request.Name,
			Description:    request.Description,
			CronExpression: request.CronExpression,
			Timezone:       request.Timezone,
			TaskQuery:      request.TaskQuery,
		})
		if err != nil {
			writeScheduleError(w, deps, err)
			return
		}
		deps.WriteJSON(w, http.StatusOK, scheduleResponse(*row))
	case http.MethodDelete:
		if err := deps.Service.Delete(r.Context(), scheduleID, userID); err != nil {
			writeScheduleError(w, deps, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func handleScheduleRuns(w http.ResponseWriter, r *http.Request, deps SchedulesDeps, scheduleID string) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	limit, offset := schedulePagination(r)
	rows, total, err := deps.Service.Runs(r.Context(), scheduleID, deps.UserID(r), limit, offset)
	if err != nil {
		writeScheduleError(w, deps, err)
		return
	}
	items := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		items = append(items, scheduleRunResponse(row))
	}
	deps.WriteJSON(w, http.StatusOK, map[string]any{
		"runs":        items,
		"total_count": total,
		"page":        offset/limit + 1,
		"page_size":   limit,
	})
}

func handleScheduleStateChange(w http.ResponseWriter, r *http.Request, deps SchedulesDeps, scheduleID, action string) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var request struct {
		Reason string `json:"reason"`
	}
	if err := decodeScheduleRequest(r, &request); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	var (
		row *usecase.ScheduleRecord
		err error
	)
	if action == "pause" {
		row, err = deps.Service.Pause(r.Context(), scheduleID, deps.UserID(r), request.Reason)
	} else {
		row, err = deps.Service.Resume(r.Context(), scheduleID, deps.UserID(r), request.Reason)
	}
	if err != nil {
		writeScheduleError(w, deps, err)
		return
	}
	deps.WriteJSON(w, http.StatusOK, scheduleResponse(*row))
}

func decodeScheduleRequest(r *http.Request, destination any) error {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("invalid request body: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("invalid request body: multiple JSON values")
	}
	return nil
}

func schedulePagination(r *http.Request) (int, int) {
	size := 50
	page := 1
	if n, err := strconv.Atoi(r.URL.Query().Get("page_size")); err == nil && n > 0 && n <= 100 {
		size = n
	}
	if n, err := strconv.Atoi(r.URL.Query().Get("page")); err == nil && n > 0 {
		page = n
	}
	return size, (page - 1) * size
}

func scheduleResponse(row usecase.ScheduleRecord) map[string]any {
	return map[string]any{
		"schedule_id":     row.ScheduleID,
		"name":            row.Name,
		"description":     row.Description,
		"cron_expression": row.CronExpression,
		"timezone":        row.Timezone,
		"task_query":      row.TaskQuery,
		"status":          strings.ToUpper(row.Status),
		"total_runs":      row.TotalRuns,
		"successful_runs": row.SuccessfulRuns,
		"failed_runs":     row.FailedRuns,
		"created_at":      row.CreatedAt.UTC().Format(time.RFC3339),
	}
}

func scheduleRunResponse(row usecase.ScheduleRunRow) map[string]any {
	response := map[string]any{
		"workflow_id":    row.TaskID,
		"query":          row.TaskQuery,
		"status":         scheduleRunStatus(row.Status),
		"result":         row.Result,
		"error_message":  row.Error,
		"total_tokens":   row.Usage.TotalTokens,
		"total_cost_usd": row.Usage.TotalCostUSD,
		"triggered_at":   row.TriggeredAt.UTC().Format(time.RFC3339),
	}
	if row.DurationMS != nil {
		response["duration_ms"] = *row.DurationMS
	}
	if row.StartedAt != nil {
		response["started_at"] = row.StartedAt.UTC().Format(time.RFC3339)
	}
	if row.CompletedAt != nil {
		response["completed_at"] = row.CompletedAt.UTC().Format(time.RFC3339)
	}
	return response
}

func scheduleRunStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "completed":
		return "COMPLETED"
	case "failed", "cancelled":
		return "FAILED"
	case "pending", "queued", "dispatching", "running":
		return "RUNNING"
	default:
		return "UNKNOWN"
	}
}

func writeScheduleError(w http.ResponseWriter, deps SchedulesDeps, err error) {
	if errors.Is(err, pgx.ErrNoRows) {
		http.Error(w, "schedule not found", http.StatusNotFound)
		return
	}
	deps.WriteJSON(w, http.StatusBadRequest, map[string]any{"error": err.Error()})
}
