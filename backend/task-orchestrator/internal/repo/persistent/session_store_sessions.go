package persistent

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"
)

func (s *SessionStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	if s == nil {
		return "", fmt.Errorf("session store not initialized")
	}
	if s.redisEnabled() {
		if sid, err := s.redisGetString(ctx, taskSessionKey(taskID)); err == nil && sid != "" {
			return sid, nil
		}
	}
	if s.pg == nil {
		return "", fmt.Errorf("postgres not configured")
	}
	var sessionID string
	err := s.pg.QueryRow(ctx, `SELECT session_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&sessionID)
	if err == nil && s.redisEnabled() && sessionID != "" {
		_ = s.redisSetString(ctx, taskSessionKey(taskID), sessionID, 24*time.Hour)
	}
	return sessionID, err
}

func (s *SessionStore) GetSession(ctx context.Context, sessionID, userID string) (*SessionRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	cacheKey := sessionCacheKey(userID, sessionID, "detail")
	var cached SessionRow
	if s.cacheGetJSON(ctx, cacheKey, &cached) {
		s.touchSessionActivity(ctx, sessionID, userID)
		return &cached, nil
	}

	row := &SessionRow{}
	err := s.pg.QueryRow(ctx, `
        SELECT
            s.session_id,
            s.user_id,
            s.title,
            s.pinned,
            s.task_count,
            COALESCE(u.total_tokens, 0) AS tokens_used,
            COALESCE(u.total_cost_usd, 0) AS total_cost_usd,
            s.created_at,
            s.updated_at,
            s.last_activity_at,
            s.latest_task_query,
            s.latest_task_status
        FROM kc_sessions s
        LEFT JOIN (
            SELECT
                session_id,
                user_id,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
            FROM kc_llm_usage_ledger
            WHERE session_id = $1 AND user_id = $2
            GROUP BY session_id, user_id
        ) u ON u.session_id = s.session_id AND u.user_id = s.user_id
        WHERE s.session_id = $1 AND s.user_id = $2
    `, sessionID, userID).Scan(
		&row.SessionID,
		&row.UserID,
		&row.Title,
		&row.Pinned,
		&row.TaskCount,
		&row.TokensUsed,
		&row.TotalCostUSD,
		&row.CreatedAt,
		&row.UpdatedAt,
		&row.LastActivityAt,
		&row.LatestTaskQuery,
		&row.LatestTaskStatus,
	)
	if err != nil {
		return nil, err
	}
	s.cacheSetJSON(ctx, cacheKey, row)
	s.touchSessionActivity(ctx, sessionID, userID)
	return row, nil
}

func (s *SessionStore) ListSessions(ctx context.Context, userID string, limit, offset int) ([]SessionRow, int, error) {
	if s == nil || s.pg == nil {
		return nil, 0, fmt.Errorf("postgres not configured")
	}
	var total int
	if err := s.pg.QueryRow(ctx, `SELECT COUNT(*) FROM kc_sessions WHERE user_id = $1`, userID).Scan(&total); err != nil {
		return nil, 0, err
	}
	rows, err := s.pg.Query(ctx, `
        SELECT
            s.session_id,
            s.user_id,
            s.title,
            s.pinned,
            s.task_count,
            COALESCE(u.total_tokens, 0) AS tokens_used,
            COALESCE(u.total_cost_usd, 0) AS total_cost_usd,
            s.created_at,
            s.updated_at,
            s.last_activity_at,
            s.latest_task_query,
            s.latest_task_status
        FROM kc_sessions s
        LEFT JOIN (
            SELECT
                session_id,
                user_id,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(total_cost_usd::double precision), 0) AS total_cost_usd
            FROM kc_llm_usage_ledger
            WHERE user_id = $1
            GROUP BY session_id, user_id
        ) u ON u.session_id = s.session_id AND u.user_id = s.user_id
        WHERE s.user_id = $1
        ORDER BY s.pinned DESC, s.updated_at DESC NULLS LAST
        LIMIT $2 OFFSET $3
    `, userID, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	sessions := make([]SessionRow, 0)
	for rows.Next() {
		row := SessionRow{}
		if err := rows.Scan(
			&row.SessionID,
			&row.UserID,
			&row.Title,
			&row.Pinned,
			&row.TaskCount,
			&row.TokensUsed,
			&row.TotalCostUSD,
			&row.CreatedAt,
			&row.UpdatedAt,
			&row.LastActivityAt,
			&row.LatestTaskQuery,
			&row.LatestTaskStatus,
		); err != nil {
			return nil, 0, err
		}
		sessions = append(sessions, row)
	}
	return sessions, total, rows.Err()
}

func (s *SessionStore) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	setParts := []string{}
	args := []any{sessionID, userID}
	argPos := 3
	if title != nil {
		setParts = append(setParts, "title = $"+strconv.Itoa(argPos))
		args = append(args, title)
		argPos++
	}
	if pinned != nil {
		setParts = append(setParts, "pinned = $"+strconv.Itoa(argPos))
		args = append(args, pinned)
		argPos++
	}
	if len(setParts) == 0 {
		return nil
	}
	setParts = append(setParts, "updated_at = NOW()")
	query := "UPDATE kc_sessions SET " + strings.Join(setParts, ", ") + " WHERE session_id = $1 AND user_id = $2"
	_, err := s.pg.Exec(ctx, query, args...)
	if err == nil {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	if s == nil || s.pg == nil {
		return 0, fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `DELETE FROM kc_sessions WHERE session_id = $1 AND user_id = $2`, sessionID, userID)
	if err != nil {
		return 0, err
	}
	s.invalidateSessionCache(ctx, sessionID, userID)
	s.deleteWorkspace(ctx, sessionID)
	return cmd.RowsAffected(), nil
}

func (s *SessionStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]TaskRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	cacheKey := sessionCacheKey(userID, sessionID, "history")
	var cached []TaskRow
	if s.cacheGetJSON(ctx, cacheKey, &cached) {
		return cached, nil
	}
	rows, err := s.pg.Query(ctx, `
        SELECT task_id, task_id AS workflow_id, query, status, task_type, result, error_message, created_at, completed_at
        FROM kc_tasks
        WHERE session_id = $1 AND user_id = $2
        ORDER BY created_at ASC
    `, sessionID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	tasks := make([]TaskRow, 0)
	for rows.Next() {
		row := TaskRow{}
		if err := rows.Scan(
			&row.TaskID,
			&row.WorkflowID,
			&row.Query,
			&row.Status,
			&row.TaskType,
			&row.Result,
			&row.Error,
			&row.StartedAt,
			&row.CompletedAt,
		); err != nil {
			return nil, err
		}
		if row.StartedAt != nil && row.CompletedAt != nil {
			d := row.CompletedAt.Sub(*row.StartedAt).Milliseconds()
			row.DurationMS = &d
		}
		tasks = append(tasks, row)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	s.cacheSetJSON(ctx, cacheKey, tasks)
	s.touchSessionActivity(ctx, sessionID, userID)
	return tasks, nil
}

func (s *SessionStore) GetTask(ctx context.Context, taskID, userID string) (*TaskRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	row := TaskRow{}
	err := s.pg.QueryRow(ctx, `
        SELECT task_id, task_id AS workflow_id, query, status, task_type, result, error_message, created_at, completed_at
        FROM kc_tasks
        WHERE task_id = $1 AND user_id = $2
    `, taskID, userID).Scan(
		&row.TaskID,
		&row.WorkflowID,
		&row.Query,
		&row.Status,
		&row.TaskType,
		&row.Result,
		&row.Error,
		&row.StartedAt,
		&row.CompletedAt,
	)
	if err != nil {
		return nil, err
	}
	if row.StartedAt != nil && row.CompletedAt != nil {
		duration := row.CompletedAt.Sub(*row.StartedAt).Milliseconds()
		row.DurationMS = &duration
	}
	return &row, nil
}
