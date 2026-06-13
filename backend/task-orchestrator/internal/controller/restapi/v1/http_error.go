package restapi

type apiErrorBody struct {
	Error apiError `json:"error"`
}

type apiError struct {
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
}

const (
	errCodeActiveTaskExists          = "active-task-exists"
	errCodeNoActiveTask              = "no-active-task"
	errCodeInvalidTransition         = "invalid-transition"
	errCodeAuthzDenied               = "authz-denied"
	errCodeUnauthenticated           = "unauthenticated"
	errCodeAuthProviderUnavailable   = "auth-provider-unavailable"
	errCodeIdempotencyKeyRequired    = "idempotency-key-required"
	errCodeIdempotencyReplayMismatch = "idempotency-key-replay-mismatch"
)
