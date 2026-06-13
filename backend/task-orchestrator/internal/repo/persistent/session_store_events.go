package persistent

import (
	"context"
	"fmt"
	"time"
)

func (s *SessionStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("postgres not configured")
	}
	var payloadJSON any = nil
	if payload != "" {
		payloadJSON = payload
	}
	_, err := s.pg.Exec(ctx, `
	        INSERT INTO kc_events (session_id, task_id, workflow_id, event_type, message, payload, stream_id, created_at)
	        SELECT $1::varchar, $2::varchar, $3::varchar, $4::varchar, $5::text, $6::jsonb, $7::varchar, $8::timestamptz
	        WHERE COALESCE($7::varchar, '') = '' OR NOT EXISTS (
	            SELECT 1 FROM kc_events
	            WHERE task_id = $2::varchar
	              AND event_type = $4::varchar
	              AND stream_id = $7::varchar
	        )
	    `, sessionID, taskID, workflowID, eventType, message, payloadJSON, streamID, ts)
	if err == nil {
		_, _ = s.pg.Exec(ctx, `
            UPDATE kc_sessions
            SET last_activity_at = $2,
                updated_at = $2,
                latest_task_status = $3
            WHERE session_id = $1
        `, sessionID, ts.UTC(), eventType)
		s.invalidateSessionCache(ctx, sessionID, "")
	}
	return err
}

func (s *SessionStore) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]EventRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, `
        SELECT id, task_id, workflow_id, event_type, message, payload::text, stream_id, created_at
        FROM kc_events
        WHERE session_id = $1
        ORDER BY id ASC
        LIMIT $2 OFFSET $3
    `, sessionID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]EventRow, 0)
	for rows.Next() {
		row := EventRow{}
		if err := rows.Scan(
			&row.ID,
			&row.TaskID,
			&row.Workflow,
			&row.Type,
			&row.Message,
			&row.Payload,
			&row.StreamID,
			&row.Timestamp,
		); err != nil {
			return nil, err
		}
		events = append(events, row)
	}
	return events, rows.Err()
}

func (s *SessionStore) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]EventRow, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("postgres not configured")
	}
	rows, err := s.pg.Query(ctx, `
        SELECT id, task_id, workflow_id, event_type, message, payload::text, stream_id, created_at
        FROM kc_events
        WHERE workflow_id = $1
        ORDER BY id ASC
        LIMIT $2 OFFSET $3
    `, workflowID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]EventRow, 0)
	for rows.Next() {
		row := EventRow{}
		if err := rows.Scan(
			&row.ID,
			&row.TaskID,
			&row.Workflow,
			&row.Type,
			&row.Message,
			&row.Payload,
			&row.StreamID,
			&row.Timestamp,
		); err != nil {
			return nil, err
		}
		events = append(events, row)
	}
	return events, rows.Err()
}
