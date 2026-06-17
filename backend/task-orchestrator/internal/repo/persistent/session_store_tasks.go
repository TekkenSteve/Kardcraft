package persistent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

func (s *SessionStore) UpsertSession(ctx context.Context, sessionID, userID, latestQuery, latestStatus string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `
        INSERT INTO kc_sessions
            (session_id, user_id, title, task_count, tokens_used, created_at, updated_at, last_activity_at, latest_task_query, latest_task_status)
        VALUES
            ($1, $2, NULL, 1, 0, NOW(), NOW(), NOW(), $3, $4)
        ON CONFLICT (session_id) DO UPDATE
            SET updated_at = NOW(),
                last_activity_at = NOW(),
                latest_task_query = EXCLUDED.latest_task_query,
                latest_task_status = EXCLUDED.latest_task_status,
                user_id = EXCLUDED.user_id,
                task_count = COALESCE(kc_sessions.task_count, 0) + 1
    `, sessionID, userID, latestQuery, latestStatus)
	if err == nil {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) UpsertTask(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	_, err := s.pg.Exec(ctx, `
        INSERT INTO kc_tasks
            (task_id, session_id, user_id, task_type, status, query, created_at, updated_at)
        VALUES
            ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        ON CONFLICT (task_id) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = NOW(),
                query = EXCLUDED.query
	`, taskID, sessionID, userID, taskType, status, query)
	if err == nil {
		if s.redisEnabled() {
			_ = s.redisSetString(ctx, taskSessionKey(taskID), sessionID, 24*time.Hour)
		}
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	if s == nil || s.pg == nil {
		return false, fmt.Errorf("postgres not configured")
	}
	cmd, err := s.pg.Exec(ctx, `
        INSERT INTO kc_tasks
            (task_id, session_id, user_id, task_type, status, query, created_at, updated_at)
        SELECT
            $1::text, $2::text, $3::text, $4::text, $5::text, $6::text, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1
            FROM kc_tasks
            WHERE session_id::text = $2::text
              AND user_id::text = $3::text
              AND LOWER(COALESCE(status::text, '')) IN ('pending', 'queued', 'running', 'paused')
        )
        ON CONFLICT (task_id) DO NOTHING
    `, taskID, sessionID, userID, taskType, status, query)
	if err != nil {
		return false, err
	}
	inserted := cmd.RowsAffected() > 0
	if inserted {
		if s.redisEnabled() {
			_ = s.redisSetString(ctx, taskSessionKey(taskID), sessionID, 24*time.Hour)
		}
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return inserted, nil
}

func (s *SessionStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	sessionID, _ := s.GetTaskSession(ctx, taskID)
	userID := ""
	if sessionID != "" {
		_ = s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&userID)
	}
	if strings.TrimSpace(errMsg) == "" {
		_, err := s.pg.Exec(ctx, `
            UPDATE kc_tasks
            SET status = $2, updated_at = NOW()
            WHERE task_id = $1
        `, taskID, status)
		if err == nil && sessionID != "" {
			s.invalidateSessionCache(ctx, sessionID, userID)
			s.touchSessionActivity(ctx, sessionID, userID)
		}
		return err
	}
	_, err := s.pg.Exec(ctx, `
        UPDATE kc_tasks
        SET status = $2, error_message = $3, updated_at = NOW()
        WHERE task_id = $1
    `, taskID, status, errMsg)
	if err == nil && sessionID != "" {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return err
}

func (s *SessionStore) UpdateTaskFinalState(
	ctx context.Context,
	taskID string,
	status string,
	result any,
	errMsg string,
	completedAt time.Time,
) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	status = strings.TrimSpace(status)
	if status == "" {
		return fmt.Errorf("status is required")
	}
	if completedAt.IsZero() {
		completedAt = time.Now().UTC()
	} else {
		completedAt = completedAt.UTC()
	}

	sessionID, _ := s.GetTaskSession(ctx, taskID)
	userID := ""
	if sessionID != "" {
		_ = s.pg.QueryRow(ctx, `SELECT user_id FROM kc_tasks WHERE task_id = $1`, taskID).Scan(&userID)
	}

	var resultJSON any
	if result != nil {
		raw, err := json.Marshal(result)
		if err != nil {
			return fmt.Errorf("marshal task result: %w", err)
		}
		resultJSON = raw
	}

	tx, err := s.pg.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `
        UPDATE kc_tasks
        SET status = $2,
            result = COALESCE($3::jsonb, result),
            error_message = NULLIF($4, ''),
            completed_at = $5,
            updated_at = NOW()
        WHERE task_id = $1
    `, taskID, status, resultJSON, strings.TrimSpace(errMsg), completedAt); err != nil {
		return err
	}

	if sessionID != "" {
		if _, err := tx.Exec(ctx, `
	            UPDATE kc_sessions
	            SET latest_task_status = $2,
	                updated_at = $3,
	                last_activity_at = $3
	            WHERE session_id = $1
	        `, sessionID, status, completedAt); err != nil {
			return err
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return err
	}

	if sessionID != "" {
		s.invalidateSessionCache(ctx, sessionID, userID)
		s.touchSessionActivity(ctx, sessionID, userID)
	}
	return nil
}
