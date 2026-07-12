package agentosconfig

import (
	"testing"
	"time"
)

func TestScheduleTriggerConfigFromEnvBuildsExplicitPolicy(t *testing.T) {
	setScheduleTriggerEnv(t)

	config, err := ScheduleTriggerConfigFromEnv()
	if err != nil {
		t.Fatalf("ScheduleTriggerConfigFromEnv() error = %v", err)
	}
	if config.CatchupWindow != 5*time.Minute {
		t.Fatalf("CatchupWindow = %v, want 5m", config.CatchupWindow)
	}
	if config.Delivery.StartToCloseTimeout != 30*time.Second {
		t.Fatalf("StartToCloseTimeout = %v, want 30s", config.Delivery.StartToCloseTimeout)
	}
	if config.Delivery.Retry.MaximumAttempts != 0 {
		t.Fatalf("MaximumAttempts = %d, want 0", config.Delivery.Retry.MaximumAttempts)
	}
}

func TestScheduleTriggerConfigFromEnvRejectsIncompletePolicy(t *testing.T) {
	setScheduleTriggerEnv(t)
	t.Setenv(EnvScheduleRetryMaximum, "")

	if _, err := ScheduleTriggerConfigFromEnv(); err == nil {
		t.Fatal("ScheduleTriggerConfigFromEnv() error = nil, want required setting error")
	}
}

func setScheduleTriggerEnv(t *testing.T) {
	t.Helper()
	t.Setenv(EnvScheduleCatchupWindow, "5m")
	t.Setenv(EnvScheduleDeliveryTimeout, "30s")
	t.Setenv(EnvScheduleRetryInitial, "1s")
	t.Setenv(EnvScheduleRetryMaximum, "1m")
	t.Setenv(EnvScheduleRetryBackoff, "2")
	t.Setenv(EnvScheduleRetryAttempts, "0")
}
