package stream

import (
	"context"
	"strings"

	"task-orchestrator/internal/usecase"
)

type InsertUsageFunc func(ctx context.Context, row usecase.UsageLedgerRow) (bool, error)
type CounterIncFunc func()

type UsageProjector struct {
	insertUsage        InsertUsageFunc
	logf               func(string, ...any)
	onIngested         CounterIncFunc
	onDeduped          CounterIncFunc
	onFailed           CounterIncFunc
	onInvalid          CounterIncFunc
	onSchemaMismatched CounterIncFunc
}

func NewUsageProjector(
	insertUsage InsertUsageFunc,
	logf func(string, ...any),
	onIngested CounterIncFunc,
	onDeduped CounterIncFunc,
	onFailed CounterIncFunc,
	onInvalid CounterIncFunc,
	onSchemaMismatched CounterIncFunc,
) *UsageProjector {
	return &UsageProjector{
		insertUsage:        insertUsage,
		logf:               logf,
		onIngested:         onIngested,
		onDeduped:          onDeduped,
		onFailed:           onFailed,
		onInvalid:          onInvalid,
		onSchemaMismatched: onSchemaMismatched,
	}
}

func (p *UsageProjector) Project(ctx context.Context, ev NormalizedEvent) {
	if p == nil || p.insertUsage == nil {
		return
	}
	if !strings.EqualFold(strings.TrimSpace(ev.EventType), "LLM_USAGE") {
		return
	}
	row, ok, reason := BuildUsageLedgerRow(ev.Payload, ev.WorkflowID, ev.TaskID, ev.SessionID)
	if ok {
		inserted, err := p.insertUsage(ctx, row)
		if err != nil {
			if p.onFailed != nil {
				p.onFailed()
			}
			if p.logf != nil {
				p.logf("llm usage ingest failed workflow_id=%s task_id=%s stream_id=%s err=%v", ev.WorkflowID, ev.TaskID, ev.StreamID, err)
			}
			return
		}
		if !inserted {
			if p.onDeduped != nil {
				p.onDeduped()
			}
			if p.logf != nil {
				p.logf("llm usage duplicate dropped workflow_id=%s task_id=%s stream_id=%s idempotency_key=%s", ev.WorkflowID, ev.TaskID, ev.StreamID, row.IdempotencyKey)
			}
			return
		}
		if p.onIngested != nil {
			p.onIngested()
		}
		return
	}

	if reason == "schema_mismatch" {
		if p.onSchemaMismatched != nil {
			p.onSchemaMismatched()
		}
	} else if p.onInvalid != nil {
		p.onInvalid()
	}
	if p.logf != nil {
		p.logf("llm usage payload invalid workflow_id=%s task_id=%s stream_id=%s reason=%s payload=%v", ev.WorkflowID, ev.TaskID, ev.StreamID, reason, ev.Payload)
	}
}
