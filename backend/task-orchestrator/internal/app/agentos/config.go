package agentosconfig

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"
	agentosproc "github.com/TekkenSteve/GoAgent/agentos/process"
	agentostemporal "github.com/TekkenSteve/GoAgent/agentos/temporal"

	"task-orchestrator/internal/repo/persistent"
)

const (
	EnvAgentWorkflowBackendName = "AGENT_WORKFLOW_BACKEND_NAME"
	EnvAgentWorkflowTaskQueue   = "AGENT_WORKFLOW_TASK_QUEUE"
	EnvAgentWorkflowType        = "AGENT_WORKFLOW_TYPE"
	EnvScheduleCatchupWindow    = "KARDCRAFT_SCHEDULE_CATCHUP_WINDOW"
	EnvScheduleDeliveryTimeout  = "KARDCRAFT_SCHEDULE_DELIVERY_TIMEOUT"
	EnvScheduleRetryInitial     = "KARDCRAFT_SCHEDULE_RETRY_INITIAL_INTERVAL"
	EnvScheduleRetryMaximum     = "KARDCRAFT_SCHEDULE_RETRY_MAXIMUM_INTERVAL"
	EnvScheduleRetryBackoff     = "KARDCRAFT_SCHEDULE_RETRY_BACKOFF_COEFFICIENT"
	EnvScheduleRetryAttempts    = "KARDCRAFT_SCHEDULE_RETRY_MAXIMUM_ATTEMPTS"

	externalStatusQuery       = "agentos_status"
	externalUserMessageSignal = "user_input"
	externalPauseSignal       = "pause"
	externalResumeSignal      = "resume"
	externalCancelSignal      = "cancel"
)

type ExternalRuntimeConfig struct {
	Backend agentos.BackendRef
	Runtime agentostemporal.RuntimeConfig
}

// ScheduleTriggerConfig is Kardcraft's explicit recurring delivery policy.
// It is intentionally independent of any Temporal implementation details.
type ScheduleTriggerConfig struct {
	CatchupWindow time.Duration
	Delivery      agentosproc.TriggerDeliveryPolicy
}

func ExternalRuntimeConfigFromEnv(storeCfg persistent.SessionStoreConfig) (ExternalRuntimeConfig, error) {
	backendName, err := requiredEnv(EnvAgentWorkflowBackendName)
	if err != nil {
		return ExternalRuntimeConfig{}, err
	}
	taskQueue, err := requiredEnv(EnvAgentWorkflowTaskQueue)
	if err != nil {
		return ExternalRuntimeConfig{}, err
	}
	workflowType, err := requiredEnv(EnvAgentWorkflowType)
	if err != nil {
		return ExternalRuntimeConfig{}, err
	}
	redisURL, err := storeCfg.RedisURL()
	if err != nil {
		return ExternalRuntimeConfig{}, fmt.Errorf("invalid redis configuration: %w", err)
	}

	backend := agentos.BackendRef{
		Kind: agentos.BackendKindTemporalExternal,
		Name: backendName,
	}

	return ExternalRuntimeConfig{
		Backend: backend,
		Runtime: agentostemporal.RuntimeConfig{
			TemporalTaskQueues: agentostemporal.DefaultTaskQueues(),
			PostgresURL:        storeCfg.PostgresDSN,
			RedisURL:           redisURL,
			ArtifactStore:      artifactStoreConfigFromEnv(),
			TemporalExternalBackends: []agentostemporal.ExternalBackendConfig{
				{
					Name:         backend.Name,
					TaskQueue:    taskQueue,
					WorkflowType: workflowType,
					QueryType:    externalStatusQuery,
					Signals: agentostemporal.ExternalSignalNames{
						Pause:  externalPauseSignal,
						Resume: externalResumeSignal,
						Cancel: externalCancelSignal,
						Defaults: map[agentoscore.SignalType]string{
							agentoscore.SignalUserMessage: externalUserMessageSignal,
						},
					},
				},
			},
		},
	}, nil
}

func artifactStoreConfigFromEnv() agentostemporal.ArtifactStoreConfig {
	backend := agentostemporal.ArtifactStoreBackend(strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_STORE_BACKEND")))
	if backend == "" {
		backend = agentostemporal.ArtifactStoreBackendS3
	}

	return agentostemporal.ArtifactStoreConfig{
		Backend: backend,
		Local: agentostemporal.LocalArtifactStoreConfig{
			Root: strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_LOCAL_ROOT")),
		},
		S3: agentostemporal.S3ArtifactStoreConfig{
			Bucket:          strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_S3_BUCKET")),
			Region:          strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_S3_REGION")),
			Endpoint:        strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_S3_ENDPOINT")),
			AccessKeyID:     strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_S3_ACCESS_KEY_ID")),
			SecretAccessKey: strings.TrimSpace(os.Getenv("GOAGENT_ARTIFACT_S3_SECRET_ACCESS_KEY")),
			ForcePathStyle:  envBool("GOAGENT_ARTIFACT_S3_FORCE_PATH_STYLE"),
		},
	}
}

func envBool(key string) bool {
	value, err := strconv.ParseBool(strings.TrimSpace(os.Getenv(key)))
	return err == nil && value
}

// PlanWorkerConfig derives the plan-only worker configuration from the same
// runtime configuration used by the embedded PlanRuntime. This keeps backend
// routing and artifact persistence identical on both sides of RunPlan.
func PlanWorkerConfig(runtime agentostemporal.RuntimeConfig) agentostemporal.WorkerConfig {
	return agentostemporal.WorkerConfig{
		TemporalAddress:          runtime.TemporalAddress,
		TemporalNamespace:        runtime.TemporalNamespace,
		TemporalTaskQueues:       runtime.TemporalTaskQueues,
		PostgresURL:              runtime.PostgresURL,
		PostgresPoolMax:          runtime.PostgresPoolMax,
		RedisURL:                 runtime.RedisURL,
		ArtifactStore:            runtime.ArtifactStore,
		TemporalExternalBackends: runtime.TemporalExternalBackends,
		HTTPBackends:             runtime.HTTPBackends,
		GRPCBackends:             runtime.GRPCBackends,
	}
}

func ScheduleTriggerConfigFromEnv() (ScheduleTriggerConfig, error) {
	catchupWindow, err := requiredDurationEnv(EnvScheduleCatchupWindow)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}
	deliveryTimeout, err := requiredDurationEnv(EnvScheduleDeliveryTimeout)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}
	initialInterval, err := requiredDurationEnv(EnvScheduleRetryInitial)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}
	maximumInterval, err := requiredDurationEnv(EnvScheduleRetryMaximum)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}
	backoffCoefficient, err := requiredFloatEnv(EnvScheduleRetryBackoff)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}
	maximumAttempts, err := requiredInt32Env(EnvScheduleRetryAttempts)
	if err != nil {
		return ScheduleTriggerConfig{}, err
	}

	config := ScheduleTriggerConfig{
		CatchupWindow: catchupWindow,
		Delivery: agentosproc.TriggerDeliveryPolicy{
			StartToCloseTimeout: deliveryTimeout,
			Retry: agentosproc.TriggerDeliveryRetryPolicy{
				InitialInterval:    initialInterval,
				MaximumInterval:    maximumInterval,
				BackoffCoefficient: backoffCoefficient,
				MaximumAttempts:    maximumAttempts,
			},
		},
	}
	if err := agentosproc.ValidateTriggerPolicy(agentosproc.TriggerPolicy{
		Overlap:       agentosproc.TriggerOverlapSkip,
		CatchupWindow: config.CatchupWindow,
		Delivery:      config.Delivery,
	}); err != nil {
		return ScheduleTriggerConfig{}, fmt.Errorf("invalid Kardcraft schedule trigger configuration: %w", err)
	}

	return config, nil
}

func requiredEnv(key string) (string, error) {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return "", fmt.Errorf("%s is required", key)
	}
	return value, nil
}

func requiredDurationEnv(key string) (time.Duration, error) {
	value, err := requiredEnv(key)
	if err != nil {
		return 0, err
	}

	duration, err := time.ParseDuration(value)
	if err != nil {
		return 0, fmt.Errorf("%s must be a duration: %w", key, err)
	}

	return duration, nil
}

func requiredFloatEnv(key string) (float64, error) {
	value, err := requiredEnv(key)
	if err != nil {
		return 0, err
	}

	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be a number: %w", key, err)
	}

	return parsed, nil
}

func requiredInt32Env(key string) (int32, error) {
	value, err := requiredEnv(key)
	if err != nil {
		return 0, err
	}

	parsed, err := strconv.ParseInt(value, 10, 32)
	if err != nil {
		return 0, fmt.Errorf("%s must be a 32-bit integer: %w", key, err)
	}

	return int32(parsed), nil
}
