package persistent

import (
	"context"
	"fmt"
	"strings"

	"task-orchestrator/internal/usecase"
)

func (s *SessionStore) CreateSchedule(ctx context.Context, row usecase.ScheduleRecord) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `INSERT INTO kc_schedules (schedule_id, temporal_schedule_id, user_id, name, description, cron_expression, timezone, task_query, status) VALUES ($1,$2,$3,$4,NULLIF($5,''),$6,$7,$8,$9)`,
		row.ScheduleID, row.TemporalScheduleID, row.UserID, row.Name, row.Description, row.CronExpression, row.Timezone, row.TaskQuery, row.Status)
	return err
}

func (s *SessionStore) GetSchedule(ctx context.Context, scheduleID, userID string) (*usecase.ScheduleRecord, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	return s.scanScheduleWithSummary(s.pg.QueryRow(ctx, `
		SELECT
			s.schedule_id, s.temporal_schedule_id, s.user_id, s.name, COALESCE(s.description,''),
			s.cron_expression, s.timezone, s.task_query, s.status,
			COUNT(r.schedule_run_id) AS total_runs,
			COUNT(r.schedule_run_id) FILTER (WHERE COALESCE(t.status, r.status) = 'completed') AS successful_runs,
			COUNT(r.schedule_run_id) FILTER (WHERE COALESCE(t.status, r.status) IN ('failed', 'cancelled')) AS failed_runs,
			s.created_at, s.updated_at
		FROM kc_schedules s
		LEFT JOIN kc_schedule_runs r ON r.schedule_id = s.schedule_id
		LEFT JOIN kc_tasks t ON t.task_id = r.task_id
		WHERE s.schedule_id=$1 AND s.user_id=$2
		GROUP BY s.schedule_id
	`, scheduleID, userID))
}

func (s *SessionStore) GetScheduleByID(ctx context.Context, scheduleID string) (*usecase.ScheduleRecord, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	return s.scanSchedule(s.pg.QueryRow(ctx, `SELECT schedule_id, temporal_schedule_id, user_id, name, COALESCE(description,''), cron_expression, timezone, task_query, status, created_at, updated_at FROM kc_schedules WHERE schedule_id=$1`, scheduleID))
}

type scheduleRow interface{ Scan(...any) error }

func (s *SessionStore) scanSchedule(row scheduleRow) (*usecase.ScheduleRecord, error) {
	var result usecase.ScheduleRecord
	if err := row.Scan(&result.ScheduleID, &result.TemporalScheduleID, &result.UserID, &result.Name, &result.Description, &result.CronExpression, &result.Timezone, &result.TaskQuery, &result.Status, &result.CreatedAt, &result.UpdatedAt); err != nil {
		return nil, err
	}
	return &result, nil
}

func (s *SessionStore) scanScheduleWithSummary(row scheduleRow) (*usecase.ScheduleRecord, error) {
	var result usecase.ScheduleRecord
	if err := row.Scan(
		&result.ScheduleID,
		&result.TemporalScheduleID,
		&result.UserID,
		&result.Name,
		&result.Description,
		&result.CronExpression,
		&result.Timezone,
		&result.TaskQuery,
		&result.Status,
		&result.TotalRuns,
		&result.SuccessfulRuns,
		&result.FailedRuns,
		&result.CreatedAt,
		&result.UpdatedAt,
	); err != nil {
		return nil, err
	}
	return &result, nil
}

func (s *SessionStore) ListSchedules(ctx context.Context, userID string, limit, offset int, status string) ([]usecase.ScheduleRecord, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	var total int
	if err := s.pg.QueryRow(ctx, `SELECT COUNT(*) FROM kc_schedules WHERE user_id=$1 AND ($2='' OR status=$2)`, userID, status).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
		SELECT
			s.schedule_id, s.temporal_schedule_id, s.user_id, s.name, COALESCE(s.description,''),
			s.cron_expression, s.timezone, s.task_query, s.status,
			COUNT(r.schedule_run_id) AS total_runs,
			COUNT(r.schedule_run_id) FILTER (WHERE COALESCE(t.status, r.status) = 'completed') AS successful_runs,
			COUNT(r.schedule_run_id) FILTER (WHERE COALESCE(t.status, r.status) IN ('failed', 'cancelled')) AS failed_runs,
			s.created_at, s.updated_at
		FROM kc_schedules s
		LEFT JOIN kc_schedule_runs r ON r.schedule_id = s.schedule_id
		LEFT JOIN kc_tasks t ON t.task_id = r.task_id
		WHERE s.user_id=$1 AND ($2='' OR s.status=$2)
		GROUP BY s.schedule_id
		ORDER BY s.updated_at DESC
		LIMIT $3 OFFSET $4
	`, userID, status, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	result := make([]usecase.ScheduleRecord, 0, limit)
	for rows.Next() {
		var row usecase.ScheduleRecord
		if err := rows.Scan(&row.ScheduleID, &row.TemporalScheduleID, &row.UserID, &row.Name, &row.Description, &row.CronExpression, &row.Timezone, &row.TaskQuery, &row.Status, &row.TotalRuns, &row.SuccessfulRuns, &row.FailedRuns, &row.CreatedAt, &row.UpdatedAt); err != nil {
			return nil, 0, err
		}
		result = append(result, row)
	}
	return result, total, rows.Err()
}

func (s *SessionStore) UpdateSchedule(ctx context.Context, row usecase.ScheduleRecord) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `UPDATE kc_schedules SET name=$3, description=NULLIF($4,''), cron_expression=$5, timezone=$6, task_query=$7 WHERE schedule_id=$1 AND user_id=$2`, row.ScheduleID, row.UserID, row.Name, row.Description, row.CronExpression, row.Timezone, row.TaskQuery)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return fmt.Errorf("schedule not found")
	}
	return nil
}

func (s *SessionStore) UpdateScheduleStatus(ctx context.Context, scheduleID, status string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `UPDATE kc_schedules SET status=$2 WHERE schedule_id=$1`, scheduleID, strings.ToLower(status))
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return fmt.Errorf("schedule not found")
	}
	return nil
}

func (s *SessionStore) DeleteSchedule(ctx context.Context, scheduleID, userID string) (int64, error) {
	if s == nil || s.pg == nil {
		return 0, fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `DELETE FROM kc_schedules WHERE schedule_id=$1 AND user_id=$2`, scheduleID, userID)
	if err != nil {
		return 0, err
	}
	return cmd.RowsAffected(), nil
}

func (s *SessionStore) CreateScheduleRun(ctx context.Context, row usecase.ScheduleRunRow) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `INSERT INTO kc_schedule_runs (schedule_id, task_id, session_id, status, triggered_at) VALUES ($1,$2,$3,$4,$5)`, row.ScheduleID, row.TaskID, row.SessionID, row.Status, row.TriggeredAt)
	return err
}

func (s *SessionStore) FailScheduleRun(ctx context.Context, taskID, message string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `UPDATE kc_schedule_runs SET status='failed', error_message=$2, completed_at=NOW() WHERE task_id=$1`, taskID, strings.TrimSpace(message))
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return fmt.Errorf("schedule run not found")
	}
	return nil
}

func (s *SessionStore) ListScheduleRuns(ctx context.Context, scheduleID, userID string, limit, offset int) ([]usecase.ScheduleRunRow, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	if limit <= 0 {
		limit = 20
	}
	if offset < 0 {
		offset = 0
	}
	var total int
	if err := s.pg.QueryRow(ctx, `SELECT COUNT(*) FROM kc_schedule_runs r JOIN kc_schedules s ON s.schedule_id=r.schedule_id WHERE r.schedule_id=$1 AND s.user_id=$2`, scheduleID, userID).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
		SELECT
			r.schedule_id, r.task_id, r.session_id, r.triggered_at,
			COALESCE(t.status, r.status), COALESCE(t.result::text,''),
			COALESCE(t.error_message, r.error_message, ''), s.task_query,
			COALESCE(t.created_at, r.created_at), COALESCE(t.completed_at, r.completed_at),
			CASE
				WHEN COALESCE(t.completed_at, r.completed_at) IS NULL THEN NULL
				ELSE (EXTRACT(EPOCH FROM (COALESCE(t.completed_at, r.completed_at) - COALESCE(t.created_at, r.created_at))) * 1000)::bigint
			END
		FROM kc_schedule_runs r
		JOIN kc_schedules s ON s.schedule_id = r.schedule_id
		LEFT JOIN kc_tasks t ON t.task_id = r.task_id
		WHERE r.schedule_id=$1 AND s.user_id=$2
		ORDER BY r.triggered_at DESC
		LIMIT $3 OFFSET $4
	`, scheduleID, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	result := make([]usecase.ScheduleRunRow, 0, limit)
	for rows.Next() {
		var row usecase.ScheduleRunRow
		if err := rows.Scan(&row.ScheduleID, &row.TaskID, &row.SessionID, &row.TriggeredAt, &row.Status, &row.Result, &row.Error, &row.TaskQuery, &row.StartedAt, &row.CompletedAt, &row.DurationMS); err != nil {
			return nil, 0, err
		}
		result = append(result, row)
	}
	return result, total, rows.Err()
}
