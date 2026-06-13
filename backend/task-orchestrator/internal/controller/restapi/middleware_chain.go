package restapi

import "net/http"

// Middleware decorates an HTTP handler with cross-cutting behavior.
type Middleware func(http.Handler) http.Handler

// Chain applies middlewares from outermost to innermost.
func Chain(middlewares ...Middleware) Middleware {
	return func(final http.Handler) http.Handler {
		h := final
		for i := len(middlewares) - 1; i >= 0; i-- {
			if middlewares[i] != nil {
				h = middlewares[i](h)
			}
		}
		return h
	}
}
