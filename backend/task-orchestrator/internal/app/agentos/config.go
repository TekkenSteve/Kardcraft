package agentosconfig

import (
	"fmt"
	"os"
	"strings"

	agentos "github.com/TekkenSteve/GoAgent/agentos/control"
	agentoscore "github.com/TekkenSteve/GoAgent/agentos/core"
	agentostemporal "github.com/TekkenSteve/GoAgent/agentos/temporal"

	"task-orchestrator/internal/repo/persistent"
	"task-orchestrator/internal/usecase"
)

const (
	EnvAgentWorkflowBackendName = "AGENT_WORKFLOW_BACKEND_NAME"
	EnvAgentWorkflowTaskQueue   = "AGENT_WORKFLOW_TASK_QUEUE"
	EnvAgentWorkflowType        = "AGENT_WORKFLOW_TYPE"

	externalStatusQuery       = "agentos_status"
	externalUserMessageSignal = "user_input"
	externalPauseSignal       = "pause"
	externalResumeSignal      = "resume"
	externalCancelSignal      = "cancel"
)

type ExternalRuntimeConfig struct {
	Backend usecase.AgentBackendRef
	Runtime agentostemporal.RuntimeConfig
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

	backend := usecase.AgentBackendRef{
		Kind: string(agentos.BackendKindTemporalExternal),
		Name: backendName,
	}

	return ExternalRuntimeConfig{
		Backend: backend,
		Runtime: agentostemporal.RuntimeConfig{
			TemporalTaskQueues: agentostemporal.DefaultTaskQueues(),
			RedisURL:           redisURL,
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

func requiredEnv(key string) (string, error) {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return "", fmt.Errorf("%s is required", key)
	}
	return value, nil
}
