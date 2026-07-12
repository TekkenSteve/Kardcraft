package goagent

import (
	"context"
	"testing"
	"time"

	agentosproc "github.com/TekkenSteve/GoAgent/agentos/process"

	"task-orchestrator/internal/usecase"
)

func TestScheduleTriggerRuntimeMapsScheduleToGenericTrigger(t *testing.T) {
	runtime := &recordingTriggerRuntime{}
	adapter, err := NewScheduleTriggerRuntime(runtime, scheduleTriggerRuntimeConfig())
	if err != nil {
		t.Fatalf("NewScheduleTriggerRuntime() error = %v", err)
	}

	row := scheduleRecordForTriggerRuntime()
	if err := adapter.Create(context.Background(), row); err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if runtime.spec == nil {
		t.Fatal("expected generic trigger declaration")
	}
	if runtime.spec.TriggerID != row.ScheduleID || runtime.spec.AccountID != row.UserID {
		t.Fatalf("unexpected trigger scope: %#v", runtime.spec.TriggerRef)
	}
	if runtime.spec.Target.Kind != scheduleTriggerResourceKind || runtime.spec.Target.ResourceID != row.ScheduleID {
		t.Fatalf("unexpected target: %#v", runtime.spec.Target)
	}
	if runtime.spec.Timing.CronExpressions[0] != row.CronExpression || runtime.spec.Timing.TimeZone != row.Timezone {
		t.Fatalf("unexpected timing: %#v", runtime.spec.Timing)
	}
	if runtime.spec.Policy.Overlap != agentosproc.TriggerOverlapSkip || runtime.spec.Policy.CatchupWindow != scheduleTriggerRuntimeConfig().CatchupWindow {
		t.Fatalf("unexpected policy: %#v", runtime.spec.Policy)
	}
}

func TestScheduleTriggerRuntimeAppliesPausedStateAtCreation(t *testing.T) {
	runtime := &recordingTriggerRuntime{}
	adapter, err := NewScheduleTriggerRuntime(runtime, scheduleTriggerRuntimeConfig())
	if err != nil {
		t.Fatalf("NewScheduleTriggerRuntime() error = %v", err)
	}

	row := scheduleRecordForTriggerRuntime()
	row.Status = "paused"
	if err := adapter.Create(context.Background(), row); err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if !runtime.options.Paused {
		t.Fatal("expected paused trigger creation option")
	}
}

func TestScheduleDeliveryFromTriggerPreservesTenantScopedIdentity(t *testing.T) {
	row := scheduleRecordForTriggerRuntime()
	projectID := scheduleTriggerProjectID(row.ScheduleID)

	delivery, err := ScheduleDeliveryFromTrigger(agentosproc.TriggerDelivery{
		DeliveryID:  "delivery-1",
		TriggeredAt: time.Date(2026, 7, 12, 8, 0, 0, 0, time.UTC),
		Trigger: agentosproc.TriggerRef{
			TriggerID: row.ScheduleID,
			AccountID: row.UserID,
			ProjectID: projectID,
		},
		Target: agentosproc.ResourceRef{
			Kind:       scheduleTriggerResourceKind,
			ResourceID: row.ScheduleID,
			AccountID:  row.UserID,
			ProjectID:  projectID,
		},
	})
	if err != nil {
		t.Fatalf("ScheduleDeliveryFromTrigger() error = %v", err)
	}
	if delivery.ScheduleID != row.ScheduleID || delivery.UserID != row.UserID || delivery.ProjectID != projectID {
		t.Fatalf("unexpected schedule delivery: %#v", delivery)
	}
}

type recordingTriggerRuntime struct {
	spec    *agentosproc.TriggerSpec
	options agentosproc.TriggerCreateOptions
}

func (r *recordingTriggerRuntime) ApplyTrigger(_ context.Context, spec *agentosproc.TriggerSpec, options agentosproc.TriggerCreateOptions) error {
	r.spec = spec
	r.options = options
	return nil
}

func (*recordingTriggerRuntime) PauseTrigger(context.Context, *agentosproc.TriggerRef, string) error {
	return nil
}

func (*recordingTriggerRuntime) ResumeTrigger(context.Context, *agentosproc.TriggerRef, string) error {
	return nil
}

func (*recordingTriggerRuntime) DeleteTrigger(context.Context, *agentosproc.TriggerRef) error {
	return nil
}

func (*recordingTriggerRuntime) ObserveTrigger(context.Context, *agentosproc.TriggerRef) (agentosproc.TriggerObservation, error) {
	return agentosproc.TriggerObservation{}, nil
}

func (*recordingTriggerRuntime) TriggerNow(context.Context, *agentosproc.TriggerRef, agentosproc.TriggerNowRequest) error {
	return nil
}

func scheduleRecordForTriggerRuntime() usecase.ScheduleRecord {
	return usecase.ScheduleRecord{
		ScheduleID:     "schedule-1",
		UserID:         "user-1",
		CronExpression: "0 * * * *",
		Timezone:       "UTC",
		Status:         "active",
		CreatedAt:      time.Date(2026, 7, 12, 8, 0, 0, 0, time.UTC),
	}
}

func scheduleTriggerRuntimeConfig() ScheduleTriggerRuntimeConfig {
	return ScheduleTriggerRuntimeConfig{
		CatchupWindow: 5 * time.Minute,
		Delivery: agentosproc.TriggerDeliveryPolicy{
			StartToCloseTimeout: 30 * time.Second,
			Retry: agentosproc.TriggerDeliveryRetryPolicy{
				InitialInterval:    time.Second,
				MaximumInterval:    time.Minute,
				BackoffCoefficient: 2,
				MaximumAttempts:    0,
			},
		},
	}
}
