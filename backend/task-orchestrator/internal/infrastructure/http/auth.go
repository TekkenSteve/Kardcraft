package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

type contextKey string

const userIDContextKey contextKey = "user_id"

func (s *Server) withAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		userID := s.resolveUserID(r)
		ctx := context.WithValue(r.Context(), userIDContextKey, userID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (s *Server) resolveUserID(r *http.Request) string {
	if v := strings.TrimSpace(r.Header.Get("X-User-ID")); v != "" {
		return v
	}
	if v := strings.TrimSpace(r.URL.Query().Get("user_id")); v != "" {
		return v
	}
	if c, err := r.Cookie("ory_kratos_session"); err == nil {
		if token := strings.TrimSpace(c.Value); token != "" {
			if userID, err := s.resolveUserIDFromKratos(r.Context(), token); err == nil && userID != "" {
				return userID
			}
		}
	}
	auth := strings.TrimSpace(r.Header.Get("Authorization"))
	if after, ok := strings.CutPrefix(auth, "Bearer "); ok {
		if token := strings.TrimSpace(after); token != "" {
			if userID, err := s.resolveUserIDFromKratos(r.Context(), token); err == nil && userID != "" {
				return userID
			}
		}
	}
	return "demo-user"
}

func (s *Server) resolveUserIDFromKratos(ctx context.Context, sessionToken string) (string, error) {
	kratosURL := strings.TrimSpace(os.Getenv("KRATOS_PUBLIC_URL"))
	if kratosURL == "" {
		kratosURL = "http://kratos:4433"
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(kratosURL, "/")+"/sessions/whoami", nil)
	if err != nil {
		return "", err
	}
	req.AddCookie(&http.Cookie{Name: "ory_kratos_session", Value: sessionToken})
	client := s.httpClient
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("kratos whoami status %d", resp.StatusCode)
	}
	var whoami struct {
		Identity struct {
			ID string `json:"id"`
		} `json:"identity"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&whoami); err != nil {
		return "", err
	}
	return strings.TrimSpace(whoami.Identity.ID), nil
}

func userIDFromContext(ctx context.Context) string {
	v, _ := ctx.Value(userIDContextKey).(string)
	if v == "" {
		return "demo-user"
	}
	return v
}
