package hydra

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestIntrospectorEnforcesClientScopeAndAudience(t *testing.T) {
	tests := []struct {
		name string
		body string
		ok   bool
	}{
		{name: "accepts matching service", body: `{"active":true,"client_id":"agent-workflow","scope":"task.events.write","aud":["task-orchestrator"]}`, ok: true},
		{name: "rejects inactive token", body: `{"active":false,"client_id":"agent-workflow","scope":"task.events.write","aud":["task-orchestrator"]}`},
		{name: "rejects wrong client", body: `{"active":true,"client_id":"other-service","scope":"task.events.write","aud":["task-orchestrator"]}`},
		{name: "rejects missing scope", body: `{"active":true,"client_id":"agent-workflow","scope":"task.read","aud":["task-orchestrator"]}`},
		{name: "rejects wrong audience", body: `{"active":true,"client_id":"agent-workflow","scope":"task.events.write","aud":["other"]}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
				if request.Method != http.MethodPost || request.FormValue("token") != "service-token" {
					t.Fatalf("unexpected introspection request")
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			introspector, err := NewIntrospector(server.Client(), IntrospectionConfig{
				Endpoint: server.URL, ClientID: "orchestrator", ClientSecret: "secret",
				RequiredScope: "task.events.write", RequiredClient: "agent-workflow", RequiredAudience: "task-orchestrator",
			})
			if err != nil {
				t.Fatalf("NewIntrospector: %v", err)
			}
			err = introspector.Validate(context.Background(), "service-token")
			if test.ok && err != nil {
				t.Fatalf("Validate: %v", err)
			}
			if !test.ok && err == nil {
				t.Fatal("Validate succeeded for invalid service token")
			}
		})
	}
}
