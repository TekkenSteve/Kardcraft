package v1

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeRawJSON(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if len(body) == 0 {
		_, _ = w.Write([]byte("{}"))
		return
	}
	_, _ = w.Write(body)
}

func writeAPIError(w http.ResponseWriter, status int, code string, message string, details map[string]any) {
	writeJSON(w, status, apiErrorBody{
		Error: apiError{
			Code:    code,
			Message: message,
			Details: details,
		},
	})
}

func parseJSON(r *http.Request, out any) error {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		return err
	}
	if len(body) == 0 {
		return nil
	}
	return json.Unmarshal(body, out)
}

func nowRFC3339() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func DefaultPortFromEnv() int {
	raw := strings.TrimSpace(os.Getenv("PORT"))
	if raw == "" {
		return 50050
	}
	port, err := strconv.Atoi(raw)
	if err != nil || port <= 0 {
		return 50050
	}
	return port
}
