package restapi

import (
	"fmt"
	"log"
	"net/http"
	"runtime/debug"
)

func Recover() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if recovered := recover(); recovered != nil {
					requestID := RequestIDFromContext(r.Context())
					log.Printf("panic recovered request_id=%s method=%s path=%s err=%v\n%s", requestID, r.Method, r.URL.RequestURI(), recovered, debug.Stack())
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(http.StatusInternalServerError)
					_, _ = fmt.Fprintf(w, `{"error":{"code":"internal-server-error","message":"internal server error","details":{"request_id":"%s"}}}`+"\n", requestID)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}
