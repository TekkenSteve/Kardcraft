package httpserver

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/TekkenSteve/GoAgent/entity"

	v1dto "task-orchestrator/internal/controller/http/v1/dto"
	"task-orchestrator/internal/repo/persistence"
	"task-orchestrator/internal/usecase"
	ucdto "task-orchestrator/internal/usecase/dto"
	"task-orchestrator/internal/usecase/port"
)

func TestHandleCreateTaskBoundaries(t *testing.T) {
	t.Run("success", func(t *testing.T) {
		s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("active task conflict", func(t *testing.T) {
		store := newFakeCommandStore()
		store.inserted = false
		store.sessionTasks = []port.SessionTask{{TaskID: "active-1", Status: "running"}}
		s := newCommandTestServer(store, &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusConflict {
			t.Fatalf("expected 409, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("runtime unavailable", func(t *testing.T) {
		s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{runID: "run-1"}, false)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusServiceUnavailable {
			t.Fatalf("expected 503, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("main task without template and without resolved default returns 400", func(t *testing.T) {
		readStore := &fakeReadModelStore{ready: true}
		s := newCommandTestServerWithReadStore(newFakeCommandStore(), &fakeCommandRuntime{runID: "run-no-default"}, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello"}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusBadRequest {
			t.Fatalf("expected 400, got %d body=%s", rr.Code, rr.Body.String())
		}
		if !strings.Contains(rr.Body.String(), "configure a default template") {
			t.Fatalf("expected explicit default template guidance, got body=%s", rr.Body.String())
		}
	})

	t.Run("main task uses resolved default template when missing input template", func(t *testing.T) {
		readStore := &fakeReadModelStore{
			ready: true,
			resolvedDefaultTemplate: &ucdto.TemplateCatalogRow{
				DefaultTemplateID:      "tpl-default",
				DefaultTemplateVersion: 7,
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-with-default"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello"}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		contextPayload, ok := agentInput["context"].(map[string]any)
		if !ok {
			t.Fatalf("expected context payload, got %#v", agentInput["context"])
		}
		if got := contextPayload["template_id"]; got != "tpl-default" {
			t.Fatalf("expected template_id resolved to tpl-default, got %q", got)
		}
		if got := contextPayload["template_version"]; got != float64(7) {
			t.Fatalf("expected template_version resolved to 7, got %#v", got)
		}
	})

	t.Run("persistence failure", func(t *testing.T) {
		store := newFakeCommandStore()
		store.upsertErr = errors.New("db down")
		s := newCommandTestServer(store, &fakeCommandRuntime{runID: "run-1"}, true)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusInternalServerError {
			t.Fatalf("expected 500, got %d body=%s", rr.Code, rr.Body.String())
		}
	})

	t.Run("controller does not import runtime dto", func(t *testing.T) {
		data, err := os.ReadFile("handlers/tasks.go")
		if err != nil {
			t.Fatalf("read handlers/tasks.go: %v", err)
		}
		if strings.Contains(string(data), "internal/runtime/temporal/workflows") {
			t.Fatalf("tasks handler leaks runtime DTO import")
		}
	})

	t.Run("inherit file_ids from session history when omitted", func(t *testing.T) {
		taskID := "task-prev-1"
		payload := `{"attachments":[{"file_id":"file_hist_1","filename":"hist.pdf","size":12,"mime_type":"application/pdf"}]}`
		readStore := &fakeReadModelStore{
			ready: true,
			sessionTasks: []ucdto.TaskRow{
				{TaskID: taskID},
			},
			sessionEvents: []ucdto.EventRow{
				{TaskID: &taskID, Payload: &payload, Timestamp: time.Now().UTC()},
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-2"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		fileIDs, ok := agentInput["file_ids"].([]any)
		if !ok || len(fileIDs) != 1 || fileIDs[0] != "file_hist_1" {
			t.Fatalf("expected inherited file_ids to include file_hist_1, got %#v", agentInput["file_ids"])
		}
		effectiveFileIDs, ok := agentInput["effective_file_ids"].([]any)
		if !ok || len(effectiveFileIDs) != 1 || effectiveFileIDs[0] != "file_hist_1" {
			t.Fatalf("expected effective_file_ids to include file_hist_1, got %#v", agentInput["effective_file_ids"])
		}
	})

	t.Run("file_policy explicit_only keeps explicit file_ids only", func(t *testing.T) {
		taskID := "task-prev-2"
		payload := `{"attachments":[{"file_id":"file_hist_1","filename":"hist.pdf","size":12,"mime_type":"application/pdf"}]}`
		readStore := &fakeReadModelStore{
			ready: true,
			sessionTasks: []ucdto.TaskRow{
				{TaskID: taskID},
			},
			sessionEvents: []ucdto.EventRow{
				{TaskID: &taskID, Payload: &payload, Timestamp: time.Now().UTC()},
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-explicit"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{
				"query":"hello",
				"context":{"template_id":"tpl-1"},
				"file_policy":"explicit_only",
				"file_ids":["file_explicit_1"]
			}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		effectiveFileIDs, ok := agentInput["effective_file_ids"].([]any)
		if !ok || len(effectiveFileIDs) != 1 || effectiveFileIDs[0] != "file_explicit_1" {
			t.Fatalf("expected explicit-only effective_file_ids, got %#v", agentInput["effective_file_ids"])
		}
		contextEnvelope, ok := agentInput["context_envelope"].(map[string]any)
		if !ok {
			t.Fatalf("expected context_envelope, got %#v", agentInput["context_envelope"])
		}
		fileResolution, ok := contextEnvelope["file_resolution"].(map[string]any)
		if !ok {
			t.Fatalf("expected file_resolution in context_envelope, got %#v", contextEnvelope)
		}
		if fileResolution["policy"] != "explicit_only" {
			t.Fatalf("expected policy explicit_only, got %#v", fileResolution["policy"])
		}
	})

	t.Run("file_policy exclude removes explicit from inherited file_ids", func(t *testing.T) {
		taskID := "task-prev-3"
		payload := `{"attachments":[{"file_id":"file_hist_1","filename":"hist.pdf","size":12,"mime_type":"application/pdf"},{"file_id":"file_hist_2","filename":"hist2.pdf","size":16,"mime_type":"application/pdf"}]}`
		readStore := &fakeReadModelStore{
			ready: true,
			sessionTasks: []ucdto.TaskRow{
				{TaskID: taskID},
			},
			sessionEvents: []ucdto.EventRow{
				{TaskID: &taskID, Payload: &payload, Timestamp: time.Now().UTC()},
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-exclude"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{
				"query":"hello",
				"context":{"template_id":"tpl-1"},
				"file_policy":"exclude",
				"file_ids":["file_hist_1"]
			}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		effectiveFileIDs, ok := agentInput["effective_file_ids"].([]any)
		if !ok || len(effectiveFileIDs) != 1 || effectiveFileIDs[0] != "file_hist_2" {
			t.Fatalf("expected exclude result [file_hist_2], got %#v", agentInput["effective_file_ids"])
		}
	})

	t.Run("build context_envelope with history files cards and policy", func(t *testing.T) {
		taskID := "task-prev-4"
		payload := `{"attachments":[{"file_id":"file_hist_9","filename":"hist9.pdf","size":9,"mime_type":"application/pdf"}]}`
		readStore := &fakeReadModelStore{
			ready: true,
			sessionTasks: []ucdto.TaskRow{
				{TaskID: taskID},
			},
			sessionEvents: []ucdto.EventRow{
				{TaskID: &taskID, Payload: &payload, Timestamp: time.Now().UTC()},
			},
			workspace: map[string]any{
				"status":  "active",
				"version": int64(3),
				"cards": []any{
					map[string]any{"id": "c1", "title": "Card 1", "type": "qa"},
				},
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-envelope"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{
				"query":"给文件制卡",
				"context":{"template_id":"tpl-1"},
				"conversation_history":[{"role":"user","content":"之前问题"},{"role":"assistant","content":"之前回答"}]
			}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		contextEnvelope, ok := agentInput["context_envelope"].(map[string]any)
		if !ok {
			t.Fatalf("expected context_envelope, got %#v", agentInput["context_envelope"])
		}
		if contextEnvelope["schema_version"] != "context-envelope.v1" {
			t.Fatalf("expected schema_version context-envelope.v1, got %#v", contextEnvelope["schema_version"])
		}
		artifacts, ok := contextEnvelope["artifacts"].(map[string]any)
		if !ok {
			t.Fatalf("expected artifacts section, got %#v", contextEnvelope["artifacts"])
		}
		files, ok := artifacts["files"].([]any)
		if !ok {
			t.Fatalf("expected artifacts.files []map[string]any, got %#v", artifacts["files"])
		}
		if len(files) != 1 {
			t.Fatalf("expected one artifact file, got %#v", files)
		}
		firstFile, ok := files[0].(map[string]any)
		if !ok || firstFile["file_id"] != "file_hist_9" {
			t.Fatalf("expected file_hist_9 in artifacts.files, got %#v", files)
		}
		response := map[string]any{}
		if err := json.Unmarshal(rr.Body.Bytes(), &response); err != nil {
			t.Fatalf("decode response: %v", err)
		}
		respFileIDs, ok := response["file_ids"].([]any)
		if !ok || len(respFileIDs) != 1 || respFileIDs[0] != "file_hist_9" {
			t.Fatalf("expected response file_ids [file_hist_9], got %#v", response["file_ids"])
		}
	})

	t.Run("context_envelope compatibility normalizes malformed sections and preserves extensions", func(t *testing.T) {
		readStore := &fakeReadModelStore{ready: true}
		runtime := &fakeCommandRuntime{runID: "run-compat"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{
				"query":"hello",
				"context":{"template_id":"tpl-1"},
				"context_envelope":{
					"schema_version":"",
					"history":"invalid",
					"tool_capabilities":"invalid",
					"ext_hint":{"keep_me":true}
				}
			}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		contextEnvelope, ok := agentInput["context_envelope"].(map[string]any)
		if !ok {
			t.Fatalf("expected context_envelope, got %#v", agentInput["context_envelope"])
		}
		if contextEnvelope["schema_version"] != "context-envelope.v1" {
			t.Fatalf("expected normalized schema_version, got %#v", contextEnvelope["schema_version"])
		}
		if _, ok := contextEnvelope["history"].(map[string]any); !ok {
			t.Fatalf("expected normalized history map, got %#v", contextEnvelope["history"])
		}
		if _, ok := contextEnvelope["compatibility"].(map[string]any); !ok {
			t.Fatalf("expected compatibility section, got %#v", contextEnvelope["compatibility"])
		}
		if _, ok := contextEnvelope["ext_hint"].(map[string]any); !ok {
			t.Fatalf("expected ext_hint to be preserved, got %#v", contextEnvelope["ext_hint"])
		}
	})

	t.Run("workspace lifecycle applies ttl_expired when workspace is stale", func(t *testing.T) {
		staleAt := time.Now().UTC().Add(-96 * time.Hour).Format(time.RFC3339)
		readStore := &fakeReadModelStore{
			ready: true,
			workspace: map[string]any{
				"status":     "active",
				"updated_at": staleAt,
				"version":    int64(2),
				"cards":      []any{},
			},
		}
		runtime := &fakeCommandRuntime{runID: "run-lifecycle"}
		s, executor := newCommandTestServerWithReadStoreAndExecutor(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{"query":"hello","context":{"template_id":"tpl-1"}}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		agentInput := decodeAgentTaskInput(t, executor)
		contextEnvelope, ok := agentInput["context_envelope"].(map[string]any)
		if !ok {
			t.Fatalf("expected context_envelope, got %#v", agentInput["context_envelope"])
		}
		artifacts, ok := contextEnvelope["artifacts"].(map[string]any)
		if !ok {
			t.Fatalf("expected artifacts section, got %#v", contextEnvelope["artifacts"])
		}
		workspace, ok := artifacts["workspace"].(map[string]any)
		if !ok {
			t.Fatalf("expected artifacts.workspace section, got %#v", artifacts["workspace"])
		}
		if workspace["lifecycle_state"] != "ttl_expired" {
			t.Fatalf("expected lifecycle_state ttl_expired, got %#v", workspace["lifecycle_state"])
		}
	})

	t.Run("planner trace is persisted at task entry decision points", func(t *testing.T) {
		readStore := &fakeReadModelStore{ready: true}
		runtime := &fakeCommandRuntime{runID: "run-trace"}
		s := newCommandTestServerWithReadStore(newFakeCommandStore(), runtime, true, readStore)
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks", `{
			"task_type":"main",
			"input":{
				"query":"hello",
				"context":{"template_id":"tpl-1"},
				"file_ids":["file_explicit_1"]
			}
		}`)
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()

		s.Handler().ServeHTTP(rr, req)
		if rr.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d body=%s", rr.Code, rr.Body.String())
		}
		traceEvents := []capturedEventInsert{}
		for _, ev := range readStore.insertedEvents {
			if ev.eventType == "PLANNER_TRACE" {
				traceEvents = append(traceEvents, ev)
			}
		}
		if len(traceEvents) < 3 {
			t.Fatalf("expected at least 3 planner trace events, got %d", len(traceEvents))
		}
		var payload map[string]any
		if err := json.Unmarshal([]byte(traceEvents[0].payload), &payload); err != nil {
			t.Fatalf("decode planner trace payload: %v", err)
		}
		if payload["trace_version"] != "planner_trace.v1" {
			t.Fatalf("expected planner_trace.v1, got %#v", payload["trace_version"])
		}
	})
}

func TestHandleSessionControlRoutesRemoved(t *testing.T) {
	s := newCommandTestServer(newFakeCommandStore(), &fakeCommandRuntime{}, true)
	req := newJSONRequest(http.MethodPost, "/api/v1/sessions/s1/pause", `{"reason":"manual"}`)
	req.Header.Set("Idempotency-Key", "k1")
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rr.Code, rr.Body.String())
	}
}

func TestHandleTaskControlRequiresIdempotencyKey(t *testing.T) {
	store := newFakeCommandStore()
	s := newCommandTestServer(store, &fakeCommandRuntime{}, true)
	req := newJSONRequest(http.MethodPost, "/api/v1/tasks/task-1/pause", `{"reason":"manual"}`)
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", rr.Code, rr.Body.String())
	}
	payload := decodeAPIErrorBody(t, rr.Body.String())
	if payload.Error.Code != errCodeIdempotencyKeyRequired {
		t.Fatalf("expected %s, got %s", errCodeIdempotencyKeyRequired, payload.Error.Code)
	}
}

func TestHandleTaskControlTimelineIsIdempotentByStreamID(t *testing.T) {
	store := newFakeCommandStore()
	readStore := &fakeReadModelStore{ready: true}
	s := newCommandTestServerWithReadStore(store, &fakeCommandRuntime{}, true, readStore)

	makePauseRequest := func() *httptest.ResponseRecorder {
		req := newJSONRequest(http.MethodPost, "/api/v1/tasks/task-1/pause", `{"reason":"manual"}`)
		req.Header.Set("Idempotency-Key", "same-key")
		req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
		rr := httptest.NewRecorder()
		s.Handler().ServeHTTP(rr, req)
		return rr
	}

	first := makePauseRequest()
	if first.Code != http.StatusOK {
		t.Fatalf("expected first request 200, got %d body=%s", first.Code, first.Body.String())
	}
	second := makePauseRequest()
	if second.Code != http.StatusOK {
		t.Fatalf("expected second request 200, got %d body=%s", second.Code, second.Body.String())
	}

	pausedEvents := 0
	streamIDs := map[string]struct{}{}
	for _, ev := range readStore.insertedEvents {
		if ev.eventType != "workflow.paused" {
			continue
		}
		pausedEvents++
		streamIDs[ev.streamID] = struct{}{}
	}

	if pausedEvents != 1 {
		t.Fatalf("expected exactly 1 persisted workflow.paused event, got %d", pausedEvents)
	}
	if len(streamIDs) != 1 {
		t.Fatalf("expected stable deterministic stream_id, got %d unique IDs", len(streamIDs))
	}
}

func TestHandleTaskPlannerTrace(t *testing.T) {
	taskID := "task-trace-1"
	streamID := "planner_trace:task-trace-1:001"
	payload := `{"trace_version":"planner_trace.v1","record":{"action":"resolve_effective_file_ids","outcome":"effective=2"}}`
	readStore := &fakeReadModelStore{
		ready: true,
		workflowEvents: []ucdto.EventRow{
			{
				ID:        1,
				TaskID:    &taskID,
				Type:      "PLANNER_TRACE",
				Message:   ptrString("resolve_effective_file_ids"),
				Payload:   &payload,
				StreamID:  &streamID,
				Timestamp: time.Now().UTC(),
			},
		},
	}
	s := newCommandTestServerWithReadStore(newFakeCommandStore(), &fakeCommandRuntime{}, true, readStore)
	req := newJSONRequest(http.MethodGet, "/api/v1/tasks/task-trace-1/planner-trace", "")
	req = req.WithContext(context.WithValue(req.Context(), userIDContextKey, "u1"))
	rr := httptest.NewRecorder()

	s.Handler().ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", rr.Code, rr.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["task_id"] != taskID {
		t.Fatalf("expected task_id %s, got %#v", taskID, body["task_id"])
	}
	records, ok := body["planner_trace"].([]any)
	if !ok || len(records) != 1 {
		t.Fatalf("expected one planner_trace record, got %#v", body["planner_trace"])
	}
}

func newCommandTestServer(store *fakeCommandStore, runtime *fakeCommandRuntime, temporalEnabled bool) *Server {
	s, _ := newCommandTestServerWithReadStoreAndExecutor(store, runtime, temporalEnabled, nil)
	return s
}

func newCommandTestServerWithReadStore(store *fakeCommandStore, runtime *fakeCommandRuntime, temporalEnabled bool, readStore *fakeReadModelStore) *Server {
	s, _ := newCommandTestServerWithReadStoreAndExecutor(store, runtime, temporalEnabled, readStore)
	return s
}

func newCommandTestServerWithReadStoreAndExecutor(store *fakeCommandStore, runtime *fakeCommandRuntime, temporalEnabled bool, readStore *fakeReadModelStore) (*Server, *fakeAgentExecutor) {
	if readStore == nil {
		readStore = &fakeReadModelStore{ready: true}
	}
	repo := persistence.NewInMemoryTaskRepository()
	publisher := persistence.NewInMemoryEventPublisher()
	taskService := usecase.NewTaskService(repo, publisher, nil)
	agentExecutor := &fakeAgentExecutor{runID: "agent-run-1"}
	commandService := usecase.NewCommandService(taskService, store, agentExecutor, runtime)

	enabled := &fakeWorkflowRuntime{enabled: temporalEnabled}
	readModel := usecase.NewReadModelService(readStore)
	s := &Server{
		mux:                     http.NewServeMux(),
		taskService:             taskService,
		commandService:          commandService,
		readModel:               readModel,
		workflowSvc:             usecase.NewWorkflowService(enabled, &fakeReadModelStore{ready: true}),
		defaultModelRef:         "test-model",
		redisSvc:                &fakeRedisStreamClient{enabled: false},
		timelineByWorkflow:      make(map[string][]TimelineEvent),
		uploads:                 make(map[string]*uploadState),
		subscribers:             make(map[string]map[int]chan v1dto.OutboundEvent),
		streamReaders:           make(map[string]context.CancelFunc),
		seenStreamIDs:           make(map[string]map[string]struct{}),
		runSeqByRunID:           make(map[string]int64),
		workflowRunByWorkflowID: make(map[string]string),
	}
	s.registerRoutes()
	return s, agentExecutor
}

func newJSONRequest(method, path, body string) *http.Request {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	return req
}

func decodeAgentTaskInput(t *testing.T, executor *fakeAgentExecutor) map[string]any {
	t.Helper()
	if executor.lastReq == nil {
		t.Fatalf("expected agent executor request")
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(executor.lastReq.UserMessage), &payload); err != nil {
		t.Fatalf("decode agent user message: %v; body=%s", err, executor.lastReq.UserMessage)
	}
	return payload
}

type fakeCommandStore struct {
	upsertErr    error
	inserted     bool
	sessionTasks []port.SessionTask
}

func newFakeCommandStore() *fakeCommandStore {
	return &fakeCommandStore{
		inserted: true,
	}
}

func (f *fakeCommandStore) UpsertSession(ctx context.Context, sessionID, userID, query, status string) error {
	return f.upsertErr
}
func (f *fakeCommandStore) InsertTaskIfNoActive(ctx context.Context, taskID, sessionID, userID, taskType, status, query string) (bool, error) {
	return f.inserted, nil
}
func (f *fakeCommandStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return nil
}
func (f *fakeCommandStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]port.SessionTask, error) {
	if len(f.sessionTasks) == 0 {
		return []port.SessionTask{{TaskID: "task-1", Status: "running", TaskType: ucdto.TaskTypeMain}}, nil
	}
	return f.sessionTasks, nil
}
func (f *fakeCommandStore) EnsureSessionAccess(ctx context.Context, sessionID, userID string) error {
	return nil
}

type fakeCommandRuntime struct {
	runID     string
	startErr  error
	signalErr error
	cancelErr error
	lastCmd   ucdto.CreateTaskCommand
}

type fakeAgentExecutor struct {
	runID   string
	lastReq *entity.ExecuteRequest
	lastOp  entity.ControlOperation
}

func (f *fakeAgentExecutor) Execute(ctx context.Context, req *entity.ExecuteRequest) (entity.RunStatus, error) {
	f.lastReq = req
	runID := f.runID
	if runID == "" {
		runID = req.RunID
	}
	return entity.RunStatus{RunID: runID, LifecycleState: "created", UpdatedAt: time.Now().UTC()}, nil
}

func (f *fakeAgentExecutor) Control(ctx context.Context, runID string, op entity.ControlOperation) error {
	f.lastOp = op
	return nil
}

func (f *fakeCommandRuntime) StartTaskWorkflow(ctx context.Context, cmd ucdto.CreateTaskCommand) (string, error) {
	f.lastCmd = cmd
	if f.startErr != nil {
		return "", f.startErr
	}
	if f.runID == "" {
		return "run-default", nil
	}
	return f.runID, nil
}
func (f *fakeCommandRuntime) SignalWorkflow(ctx context.Context, taskID, signalName string, signal ucdto.ControlSignal) error {
	return f.signalErr
}
func (f *fakeCommandRuntime) CancelWorkflow(ctx context.Context, taskID string) error {
	return f.cancelErr
}

type fakeWorkflowRuntime struct {
	enabled bool
}

func (f *fakeWorkflowRuntime) Enabled() bool { return f.enabled }
func (f *fakeWorkflowRuntime) DescribeWorkflow(ctx context.Context, workflowID, runID string) (*ucdto.WorkflowDescription, error) {
	resolvedRunID := strings.TrimSpace(runID)
	if resolvedRunID == "" {
		resolvedRunID = "run-test"
	}
	now := time.Now().UTC()
	return &ucdto.WorkflowDescription{
		WorkflowID: workflowID,
		RunID:      resolvedRunID,
		Status:     "TASK_STATUS_RUNNING",
		StartTime:  now,
	}, nil
}
func (f *fakeWorkflowRuntime) GetWorkflowResult(ctx context.Context, workflowID, runID string) (any, error) {
	return nil, errors.New("not implemented")
}
func (f *fakeWorkflowRuntime) QueryWorkflowState(ctx context.Context, workflowID string) (*ucdto.WorkflowState, error) {
	return nil, errors.New("not implemented")
}
func (f *fakeWorkflowRuntime) CancelWorkflow(ctx context.Context, workflowID string) error {
	return nil
}
func (f *fakeWorkflowRuntime) ListWorkflowHistory(ctx context.Context, workflowID string) ([]ucdto.WorkflowHistoryEvent, error) {
	return nil, nil
}
func (f *fakeWorkflowRuntime) SignalWorkflow(ctx context.Context, taskID, signalName string, signal ucdto.ControlSignal) error {
	return nil
}

type fakeReadModelStore struct {
	ready          bool
	sessionTasks   []ucdto.TaskRow
	sessionEvents  []ucdto.EventRow
	workspace      map[string]any
	workflowEvents []ucdto.EventRow
	insertedEvents []capturedEventInsert

	resolvedDefaultTemplate *ucdto.TemplateCatalogRow
	resolvedDefaultErr      error
}

type capturedEventInsert struct {
	sessionID string
	taskID    string
	workflow  string
	eventType string
	message   string
	payload   string
	streamID  string
	ts        time.Time
}

func (f *fakeReadModelStore) Ready() bool { return f.ready }
func (f *fakeReadModelStore) ListSessions(ctx context.Context, userID string, limit, offset int) ([]ucdto.SessionRow, int, error) {
	return nil, 0, nil
}
func (f *fakeReadModelStore) GetSession(ctx context.Context, sessionID, userID string) (*ucdto.SessionRow, error) {
	return &ucdto.SessionRow{SessionID: sessionID, UserID: userID}, nil
}
func (f *fakeReadModelStore) UpdateSessionMeta(ctx context.Context, sessionID, userID string, title *string, pinned *bool) error {
	return nil
}
func (f *fakeReadModelStore) DeleteSession(ctx context.Context, sessionID, userID string) (int64, error) {
	return 0, nil
}
func (f *fakeReadModelStore) ListSessionTasks(ctx context.Context, sessionID, userID string) ([]ucdto.TaskRow, error) {
	return f.sessionTasks, nil
}
func (f *fakeReadModelStore) ListSessionEvents(ctx context.Context, sessionID string, limit, offset int) ([]ucdto.EventRow, error) {
	return f.sessionEvents, nil
}
func (f *fakeReadModelStore) ListWorkflowEvents(ctx context.Context, workflowID string, limit, offset int) ([]ucdto.EventRow, error) {
	return f.workflowEvents, nil
}
func (f *fakeReadModelStore) LoadWorkspace(ctx context.Context, sessionID string) (map[string]any, error) {
	if f.workspace != nil {
		return f.workspace, nil
	}
	return map[string]any{}, nil
}
func (f *fakeReadModelStore) SaveWorkspace(ctx context.Context, sessionID string, workspace map[string]any) error {
	return nil
}
func (f *fakeReadModelStore) MarkSessionActive(ctx context.Context, sessionID, userID string) error {
	return nil
}
func (f *fakeReadModelStore) GetTaskSession(ctx context.Context, taskID string) (string, error) {
	return "s1", nil
}
func (f *fakeReadModelStore) UpdateTaskStatus(ctx context.Context, taskID, status, errMsg string) error {
	return nil
}
func (f *fakeReadModelStore) GetTaskUsageSummaryMapBySession(ctx context.Context, sessionID, userID string) (map[string]ucdto.TaskUsageSummary, error) {
	return map[string]ucdto.TaskUsageSummary{}, nil
}
func (f *fakeReadModelStore) GetTaskUsageSummaryMapByTaskIDs(ctx context.Context, userID string, taskIDs []string) (map[string]ucdto.TaskUsageSummary, error) {
	return map[string]ucdto.TaskUsageSummary{}, nil
}
func (f *fakeReadModelStore) ListAccessibleTemplates(ctx context.Context, userID string, limit, offset int) ([]ucdto.TemplateCatalogRow, int, error) {
	return nil, 0, nil
}
func (f *fakeReadModelStore) GetAccessibleTemplate(ctx context.Context, userID, templateID string) (*ucdto.TemplateCatalogRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) GetUserTemplatePreference(ctx context.Context, userID string) (*ucdto.TemplateCatalogRow, error) {
	return nil, nil
}
func (f *fakeReadModelStore) GetResolvedDefaultTemplate(ctx context.Context, userID string) (*ucdto.TemplateCatalogRow, error) {
	return f.resolvedDefaultTemplate, f.resolvedDefaultErr
}
func (f *fakeReadModelStore) UpsertUserTemplatePreference(ctx context.Context, userID, templateID string, version int) error {
	return nil
}
func (f *fakeReadModelStore) InsertEvent(ctx context.Context, sessionID, taskID, workflowID, eventType, message, payload, streamID string, ts time.Time) error {
	f.insertedEvents = append(f.insertedEvents, capturedEventInsert{
		sessionID: sessionID,
		taskID:    taskID,
		workflow:  workflowID,
		eventType: eventType,
		message:   message,
		payload:   payload,
		streamID:  streamID,
		ts:        ts,
	})
	return nil
}

func ptrString(v string) *string { return &v }
func (f *fakeReadModelStore) InsertLLMUsage(ctx context.Context, row ucdto.UsageLedgerRow) (bool, error) {
	return true, nil
}

var _ port.ReadModelStore = (*fakeReadModelStore)(nil)
