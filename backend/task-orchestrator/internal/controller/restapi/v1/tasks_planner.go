package v1

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"
)

type plannerTraceRecord struct {
	Action       string   `json:"action"`
	Reason       string   `json:"reason"`
	InputRef     string   `json:"input_ref"`
	Outcome      string   `json:"outcome"`
	EvidenceRefs []string `json:"evidence_refs,omitempty"`
}

func buildPlannerTraceRecords(
	filePolicy string,
	explicitFileIDs []string,
	inheritedFileIDs []string,
	effectiveFileIDs []string,
	contextEnvelope map[string]any,
	historyCount int,
) []plannerTraceRecord {
	normalizedPolicy := normalizeFilePolicy(filePolicy)
	normalizedExplicit := dedupeNonEmptyStrings(explicitFileIDs)
	normalizedInherited := dedupeNonEmptyStrings(inheritedFileIDs)
	normalizedEffective := dedupeNonEmptyStrings(effectiveFileIDs)
	schemaVersion := strings.TrimSpace(asStringAny(contextEnvelope["schema_version"]))
	if schemaVersion == "" {
		schemaVersion = "context-envelope.v1"
	}
	return []plannerTraceRecord{
		{
			Action:   "resolve_effective_file_ids",
			Reason:   "determine file scope for current turn",
			InputRef: fmt.Sprintf("file_policy=%s explicit=%d inherited=%d", normalizedPolicy, len(normalizedExplicit), len(normalizedInherited)),
			Outcome:  fmt.Sprintf("effective=%d", len(normalizedEffective)),
			EvidenceRefs: []string{
				fmt.Sprintf("file_policy:%s", normalizedPolicy),
				fmt.Sprintf("effective_file_ids:%d", len(normalizedEffective)),
			},
		},
		{
			Action:   "build_context_envelope",
			Reason:   "provide stable planner context with compatibility guarantees",
			InputRef: fmt.Sprintf("history_count=%d", historyCount),
			Outcome:  fmt.Sprintf("schema=%s", schemaVersion),
			EvidenceRefs: []string{
				fmt.Sprintf("context_envelope:%s", schemaVersion),
			},
		},
		{
			Action:   "progressive_disclosure_gate",
			Reason:   "prefer retrieval and targeted evidence access before clarification",
			InputRef: fmt.Sprintf("effective_file_count=%d", len(normalizedEffective)),
			Outcome:  "tool_broker_first",
			EvidenceRefs: []string{
				"policy:progressive",
			},
		},
	}
}

func persistPlannerTraceEvents(
	ctx context.Context,
	deps TasksDeps,
	sessionID string,
	taskID string,
	workflowID string,
	records []plannerTraceRecord,
) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() || len(records) == 0 {
		return
	}
	for idx, record := range records {
		payloadBytes, err := json.Marshal(map[string]any{
			"trace_version": "planner_trace.v1",
			"sequence":      idx + 1,
			"record":        record,
		})
		if err != nil {
			log.Printf("failed to marshal planner trace task_id=%s session_id=%s err=%v", taskID, sessionID, err)
			continue
		}
		streamID := fmt.Sprintf("planner_trace:%s:%03d", taskID, idx+1)
		if err := deps.ReadModel.InsertEvent(
			ctx,
			sessionID,
			taskID,
			workflowID,
			"PLANNER_TRACE",
			record.Action,
			string(payloadBytes),
			streamID,
			time.Now().UTC(),
		); err != nil {
			log.Printf("failed to persist planner trace task_id=%s session_id=%s stream_id=%s err=%v", taskID, sessionID, streamID, err)
		}
	}
}

func persistWorkspaceLifecycleAuditEvent(
	ctx context.Context,
	deps TasksDeps,
	sessionID string,
	workflowID string,
	userID string,
	contextEnvelope map[string]any,
) {
	if deps.ReadModel == nil || !deps.ReadModel.Ready() {
		return
	}
	artifacts, ok := contextEnvelope["artifacts"].(map[string]any)
	if !ok {
		return
	}
	workspace, ok := artifacts["workspace"].(map[string]any)
	if !ok {
		return
	}
	lifecycleState := strings.TrimSpace(asStringAny(workspace["lifecycle_state"]))
	if lifecycleState == "" {
		return
	}
	payloadBytes, err := json.Marshal(map[string]any{
		"schema_version":   "workspace_lifecycle_audit.v1",
		"user_id":          userID,
		"session_id":       sessionID,
		"workspace_status": strings.TrimSpace(asStringAny(workspace["status"])),
		"lifecycle_state":  lifecycleState,
		"age_hours":        workspace["age_hours"],
		"ttl_policy":       workspace["ttl_policy"],
	})
	if err != nil {
		log.Printf("failed to marshal workspace lifecycle audit session_id=%s err=%v", sessionID, err)
		return
	}
	taskID := workflowID
	if strings.TrimSpace(taskID) == "" {
		taskID = fmt.Sprintf("task_audit_%d", time.Now().UTC().UnixNano())
	}
	rawStreamID := fmt.Sprintf("workspace_lifecycle:%s:%d", taskID, time.Now().UTC().UnixNano())
	sum := sha1.Sum([]byte(rawStreamID))
	streamID := "workspace_lifecycle:" + hex.EncodeToString(sum[:])
	if err := deps.ReadModel.InsertEvent(
		ctx,
		sessionID,
		taskID,
		taskID,
		"WORKSPACE_LIFECYCLE_EVALUATED",
		"Workspace lifecycle evaluated",
		string(payloadBytes),
		streamID,
		time.Now().UTC(),
	); err != nil {
		log.Printf("failed to persist workspace lifecycle audit session_id=%s task_id=%s err=%v", sessionID, taskID, err)
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
