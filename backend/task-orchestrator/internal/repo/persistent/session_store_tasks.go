package persistent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	redissvc "task-orchestrator/internal/repo/redis"
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
		if s.redisSvc != nil {
			_ = s.redisSvc.SetString(ctx, redissvc.TaskSessionKey(taskID), sessionID, 24*time.Hour)
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
		if s.redisSvc != nil {
			_ = s.redisSvc.SetString(ctx, redissvc.TaskSessionKey(taskID), sessionID, 24*time.Hour)
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

func (s *SessionStore) AppendWorkflowOutboxEvent(ctx context.Context, event WorkflowOutboxEvent) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	event.TaskID = strings.TrimSpace(event.TaskID)
	event.WorkflowID = strings.TrimSpace(event.WorkflowID)
	event.RunID = strings.TrimSpace(event.RunID)
	event.EventType = strings.TrimSpace(event.EventType)
	event.Channel = strings.TrimSpace(event.Channel)
	if event.TaskID == "" {
		return fmt.Errorf("task_id is required")
	}
	if event.WorkflowID == "" {
		return fmt.Errorf("workflow_id is required")
	}
	if event.RunID == "" {
		return fmt.Errorf("run_id is required")
	}
	if event.EventType == "" {
		return fmt.Errorf("event_type is required")
	}
	if event.Channel == "" {
		return fmt.Errorf("channel is required")
	}
	if event.Payload == nil {
		event.Payload = map[string]any{}
	}
	occurredAt := event.OccurredAt.UTC()
	if occurredAt.IsZero() {
		occurredAt = time.Now().UTC()
	}
	payloadJSON, err := json.Marshal(event.Payload)
	if err != nil {
		return fmt.Errorf("marshal outbox payload: %w", err)
	}

	tx, err := s.pg.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `
        INSERT INTO task_lifecycle_state (
            task_id,
            phase,
            accepting_progress,
            accepting_usage,
            terminal_event_emitted,
            done_event_emitted,
            updated_at
        ) VALUES (
            $1,
            'running',
            TRUE,
            TRUE,
            FALSE,
            FALSE,
            NOW()
        )
        ON CONFLICT (task_id) DO NOTHING
    `, event.TaskID); err != nil {
		return err
	}

	var phase string
	var acceptingProgress, acceptingUsage, terminalEmitted, doneEmitted bool
	if err := tx.QueryRow(ctx, `
        SELECT phase, accepting_progress, accepting_usage, terminal_event_emitted, done_event_emitted
        FROM task_lifecycle_state
        WHERE task_id = $1
        FOR UPDATE
    `, event.TaskID).Scan(&phase, &acceptingProgress, &acceptingUsage, &terminalEmitted, &doneEmitted); err != nil {
		return err
	}
	switch event.Channel {
	case "progress":
		if !acceptingProgress {
			return fmt.Errorf("progress publish rejected by lifecycle gate: task_id=%s phase=%s", event.TaskID, phase)
		}
	case "usage":
		if !acceptingUsage {
			return fmt.Errorf("usage publish rejected by lifecycle gate: task_id=%s phase=%s", event.TaskID, phase)
		}
	case "terminal":
		if terminalEmitted {
			return nil
		}
	case "done":
		if doneEmitted {
			return nil
		}
	default:
		return fmt.Errorf("unsupported outbox channel: %s", event.Channel)
	}

	var eventSeq int64
	if err := tx.QueryRow(ctx, `
        INSERT INTO task_event_seq (task_id, next_seq)
        VALUES ($1, 1)
        ON CONFLICT (task_id)
        DO UPDATE SET next_seq = task_event_seq.next_seq + 1
        RETURNING next_seq
    `, event.TaskID).Scan(&eventSeq); err != nil {
		return err
	}

	if _, err := tx.Exec(ctx, `
        INSERT INTO workflow_event_outbox (
            task_id,
            session_id,
            user_id,
            workflow_id,
            run_id,
            event_seq,
            event_type,
            channel,
            payload,
            occurred_at,
            status,
            attempt_count
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'pending', 0
        )
    `,
		event.TaskID,
		nullableString(event.SessionID),
		nullableString(event.UserID),
		event.WorkflowID,
		event.RunID,
		eventSeq,
		event.EventType,
		event.Channel,
		string(payloadJSON),
		occurredAt,
	); err != nil {
		return err
	}

	if event.Channel == "terminal" {
		if _, err := tx.Exec(ctx, `
            UPDATE task_lifecycle_state
            SET
                terminal_event_emitted = TRUE,
                phase = 'terminal',
                accepting_progress = FALSE,
                accepting_usage = FALSE,
                updated_at = NOW()
            WHERE task_id = $1
        `, event.TaskID); err != nil {
			return err
		}
	} else if event.Channel == "done" {
		if _, err := tx.Exec(ctx, `
            UPDATE task_lifecycle_state
            SET
                done_event_emitted = TRUE,
                phase = 'terminal',
                accepting_progress = FALSE,
                accepting_usage = FALSE,
                updated_at = NOW()
            WHERE task_id = $1
        `, event.TaskID); err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}
