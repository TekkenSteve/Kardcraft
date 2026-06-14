package persistent

import (
	"context"
	"log"
	"time"
)

func (s *SessionStore) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	if s == nil || s.pg == nil || sessionID == "" || userID == "" {
		return nil
	}
	_, err := s.pg.Exec(ctx, `
        UPDATE kc_sessions
        SET last_activity_at = NOW(), updated_at = NOW()
        WHERE session_id = $1 AND user_id = $2
    `, sessionID, userID)
	if err != nil {
		return err
	}
	s.touchSessionActivity(ctx, sessionID, userID)
	return nil
}

func (s *SessionStore) Close() {
	if s == nil {
		return
	}
	if s.pg != nil {
		s.pg.Close()
	}
}

func (s *SessionStore) StartLifecycle(ctx context.Context) {
	if s == nil || s.pg == nil || s.redis == nil {
		return
	}
	ticker := time.NewTicker(s.cleanupEvery)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := s.CoolInactiveSessions(ctx); err != nil {
					log.Printf("session store cooldown failed: %v", err)
				}
			}
		}
	}()
}

func (s *SessionStore) CoolInactiveSessions(ctx context.Context) error {
	if s == nil || s.pg == nil || s.redis == nil {
		return nil
	}
	cutoff := time.Now().UTC().Add(-s.activeWindow)
	rows, err := s.pg.Query(ctx, `
        SELECT session_id, user_id
        FROM kc_sessions
        WHERE COALESCE(last_activity_at, updated_at, created_at) < $1
        ORDER BY COALESCE(last_activity_at, updated_at, created_at) ASC
        LIMIT $2
    `, cutoff, s.cleanupBatch)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var sessionID, userID string
		if err := rows.Scan(&sessionID, &userID); err != nil {
			return err
		}
		s.evictHotCache(ctx, sessionID, userID)
	}
	return rows.Err()
}
