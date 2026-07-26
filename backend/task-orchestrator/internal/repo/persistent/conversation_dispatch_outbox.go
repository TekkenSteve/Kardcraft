package persistent

import (
	"context"
	"fmt"
	"time"

	"task-orchestrator/internal/usecase"
)

func (s *SessionStore) EnqueueConversationDispatch(ctx context.Context, item usecase.ConversationDispatch) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("conversation dispatch outbox unavailable")
	}
	_, err := s.pg.Exec(ctx, `
		INSERT INTO kc_conversation_dispatch_outbox (
			dispatch_id, idempotency_key, thread_id, run_id, process_id,
			account_id, project_id, dispatch_kind, payload, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
		ON CONFLICT (idempotency_key) DO NOTHING`,
		item.DispatchID, item.IdempotencyKey, item.ThreadID, item.RunID, item.ProcessID,
		item.AccountID, item.ProjectID, item.Kind, item.Payload, item.CreatedAt)
	if err != nil {
		return fmt.Errorf("enqueue conversation dispatch: %w", err)
	}
	return nil
}

func (s *SessionStore) ClaimConversationDispatches(ctx context.Context, limit int, staleAfter time.Duration) ([]usecase.ConversationDispatch, error) {
	if s == nil || s.pg == nil {
		return nil, fmt.Errorf("conversation dispatch outbox unavailable")
	}
	if limit <= 0 {
		limit = 10
	}
	if staleAfter <= 0 {
		staleAfter = time.Minute
	}
	rows, err := s.pg.Query(ctx, `
		WITH picked AS (
			SELECT dispatch_id
			FROM kc_conversation_dispatch_outbox
			WHERE (status = 'pending' AND next_attempt_at <= NOW())
			   OR (status = 'dispatching' AND updated_at <= NOW() - make_interval(secs => $2))
			ORDER BY next_attempt_at, created_at
			FOR UPDATE SKIP LOCKED
			LIMIT $1
		)
		UPDATE kc_conversation_dispatch_outbox o
		SET status = 'dispatching', attempts = attempts + 1, updated_at = NOW()
		FROM picked
		WHERE o.dispatch_id = picked.dispatch_id
		RETURNING o.dispatch_id::text, o.idempotency_key, o.thread_id, o.run_id,
			o.process_id, o.account_id, o.project_id, o.dispatch_kind,
			o.payload, o.attempts, o.created_at`, limit, staleAfter.Seconds())
	if err != nil {
		return nil, fmt.Errorf("claim conversation dispatches: %w", err)
	}
	defer rows.Close()
	items := make([]usecase.ConversationDispatch, 0, limit)
	for rows.Next() {
		var item usecase.ConversationDispatch
		if err := rows.Scan(&item.DispatchID, &item.IdempotencyKey, &item.ThreadID, &item.RunID,
			&item.ProcessID, &item.AccountID, &item.ProjectID, &item.Kind,
			&item.Payload, &item.Attempts, &item.CreatedAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *SessionStore) MarkConversationDispatchDone(ctx context.Context, dispatchID string) error {
	return s.updateConversationDispatch(ctx, dispatchID, "dispatched", "", time.Time{})
}

func (s *SessionStore) RetryConversationDispatch(ctx context.Context, dispatchID, lastError string, nextAttempt time.Time) error {
	return s.updateConversationDispatch(ctx, dispatchID, "pending", lastError, nextAttempt)
}

func (s *SessionStore) FailConversationDispatch(ctx context.Context, dispatchID, lastError string) error {
	return s.updateConversationDispatch(ctx, dispatchID, "failed", lastError, time.Time{})
}

func (s *SessionStore) updateConversationDispatch(ctx context.Context, dispatchID, status, lastError string, nextAttempt time.Time) error {
	if s == nil || s.pg == nil {
		return fmt.Errorf("conversation dispatch outbox unavailable")
	}
	_, err := s.pg.Exec(ctx, `
		UPDATE kc_conversation_dispatch_outbox
		SET status = $2::varchar, last_error = NULLIF($3, ''),
			next_attempt_at = CASE WHEN $4::timestamptz IS NULL THEN next_attempt_at ELSE $4 END,
			dispatched_at = CASE WHEN $2::varchar = 'dispatched' THEN NOW() ELSE dispatched_at END,
			updated_at = NOW()
		WHERE dispatch_id = $1::uuid`, dispatchID, status, lastError, nullableTime(nextAttempt))
	if err != nil {
		return fmt.Errorf("update conversation dispatch %s: %w", dispatchID, err)
	}
	return nil
}

func nullableTime(value time.Time) any {
	if value.IsZero() {
		return nil
	}
	return value
}
