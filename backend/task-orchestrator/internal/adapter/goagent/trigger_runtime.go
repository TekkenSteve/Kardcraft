package goagent

import (
	"context"
	"fmt"
	"strings"
	"time"

	agentosproc "github.com/TekkenSteve/GoAgent/agentos/process"

	"task-orchestrator/internal/usecase"
)

const (
	scheduleTriggerResourceKind = agentosproc.ResourceKind("kardcraft.schedule")
)

// ScheduleTriggerRuntimeConfig declares Kardcraft's delivery behavior. It is
// explicit at composition time so the adapter does not hide operational
// defaults from the application.
type ScheduleTriggerRuntimeConfig struct {
	CatchupWindow time.Duration
	Delivery      agentosproc.TriggerDeliveryPolicy
}

// ScheduleTriggerRuntime maps Kardcraft schedule declarations onto AgentOS's
// generic trigger lifecycle. Kardcraft continues to own authorization, query
// resolution, and its schedule run history.
type ScheduleTriggerRuntime struct {
	runtime agentosproc.TriggerRuntime
	config  ScheduleTriggerRuntimeConfig
}

func NewScheduleTriggerRuntime(runtime agentosproc.TriggerRuntime, config ScheduleTriggerRuntimeConfig) (*ScheduleTriggerRuntime, error) {
	if runtime == nil {
		return nil, fmt.Errorf("agentos trigger runtime is required")
	}
	if err := agentosproc.ValidateTriggerPolicy(agentosproc.TriggerPolicy{
		Overlap:       agentosproc.TriggerOverlapSkip,
		CatchupWindow: config.CatchupWindow,
		Delivery:      config.Delivery,
	}); err != nil {
		return nil, fmt.Errorf("invalid Kardcraft schedule trigger policy: %w", err)
	}

	return &ScheduleTriggerRuntime{runtime: runtime, config: config}, nil
}

func (r *ScheduleTriggerRuntime) Create(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.apply(ctx, row)
}

func (r *ScheduleTriggerRuntime) Update(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.apply(ctx, row)
}

func (r *ScheduleTriggerRuntime) Pause(ctx context.Context, row usecase.ScheduleRecord, reason string) error {
	return r.runtime.PauseTrigger(ctx, scheduleTriggerRef(row), strings.TrimSpace(reason))
}

func (r *ScheduleTriggerRuntime) Resume(ctx context.Context, row usecase.ScheduleRecord, reason string) error {
	return r.runtime.ResumeTrigger(ctx, scheduleTriggerRef(row), strings.TrimSpace(reason))
}

func (r *ScheduleTriggerRuntime) Delete(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.runtime.DeleteTrigger(ctx, scheduleTriggerRef(row))
}

func (r *ScheduleTriggerRuntime) apply(ctx context.Context, row usecase.ScheduleRecord) error {
	return r.runtime.ApplyTrigger(ctx, scheduleTriggerSpec(row, r.config), agentosproc.TriggerCreateOptions{
		Paused: row.Status == "paused",
	})
}

func scheduleTriggerSpec(row usecase.ScheduleRecord, config ScheduleTriggerRuntimeConfig) *agentosproc.TriggerSpec {
	ref := scheduleTriggerRef(row)

	return &agentosproc.TriggerSpec{
		TriggerRef: *ref,
		Target: agentosproc.ResourceRef{
			Kind:       scheduleTriggerResourceKind,
			ResourceID: row.ScheduleID,
			AccountID:  row.UserID,
			ProjectID:  scheduleTriggerProjectID(row.ScheduleID),
		},
		Timing: agentosproc.TriggerTiming{
			CronExpressions: []string{row.CronExpression},
			TimeZone:        row.Timezone,
		},
		Policy: agentosproc.TriggerPolicy{
			Overlap:       agentosproc.TriggerOverlapSkip,
			CatchupWindow: config.CatchupWindow,
			Delivery:      config.Delivery,
		},
	}
}

func scheduleTriggerRef(row usecase.ScheduleRecord) *agentosproc.TriggerRef {
	return &agentosproc.TriggerRef{
		TriggerID: row.ScheduleID,
		AccountID: row.UserID,
		ProjectID: scheduleTriggerProjectID(row.ScheduleID),
	}
}

func scheduleTriggerProjectID(scheduleID string) string {
	return "schedule:" + strings.TrimSpace(scheduleID)
}

// ScheduleDeliveryFromTrigger converts a validated generic trigger delivery
// into Kardcraft's application-owned schedule command boundary.
func ScheduleDeliveryFromTrigger(delivery agentosproc.TriggerDelivery) (usecase.ScheduleDelivery, error) {
	if err := agentosproc.ValidateTriggerDelivery(&delivery); err != nil {
		return usecase.ScheduleDelivery{}, err
	}
	if delivery.Target.Kind != scheduleTriggerResourceKind {
		return usecase.ScheduleDelivery{}, fmt.Errorf("unsupported trigger target kind %q", delivery.Target.Kind)
	}
	if delivery.Trigger.TriggerID != delivery.Target.ResourceID || delivery.Trigger.AccountID != delivery.Target.AccountID || delivery.Trigger.ProjectID != delivery.Target.ProjectID {
		return usecase.ScheduleDelivery{}, fmt.Errorf("trigger target does not match trigger scope")
	}

	return usecase.ScheduleDelivery{
		DeliveryID:  delivery.DeliveryID,
		ScheduleID:  delivery.Target.ResourceID,
		UserID:      delivery.Target.AccountID,
		ProjectID:   delivery.Target.ProjectID,
		TriggeredAt: delivery.TriggeredAt,
	}, nil
}
