package restapi

import (
	"context"
	"fmt"
	"net/http"
	"sync/atomic"
	"time"
)

type requestIDContextKey struct{}

const requestIDHeader = "X-Request-ID"

var requestIDSeq uint64

func RequestID() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			requestID := r.Header.Get(requestIDHeader)
			if requestID == "" {
				requestID = fmt.Sprintf("req-%d-%d", time.Now().UTC().UnixNano(), atomic.AddUint64(&requestIDSeq, 1))
			}
			ctx := context.WithValue(r.Context(), requestIDContextKey{}, requestID)
			w.Header().Set(requestIDHeader, requestID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func RequestIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(requestIDContextKey{}).(string); ok {
		return v
	}
	return ""
}
