"""
Configuration classes for the application.

This module contains configuration classes that are shared across
different components to avoid circular imports.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration."""
    
    # gRPC server settings
    grpc_host: str = Field(default="0.0.0.0", env="GRPC_HOST")
    grpc_port: int = Field(default=50051, env="GRPC_PORT")
    grpc_max_workers: int = Field(default=10, env="GRPC_MAX_WORKERS")
    grpc_max_message_length: int = Field(default=50 * 1024 * 1024, env="GRPC_MAX_MESSAGE_LENGTH")  # 50MB

    # Redis settings
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db: int = Field(default=0, env="REDIS_DB")
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")

    # PostgreSQL settings
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="kardcraft", env="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", env="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", env="POSTGRES_PASSWORD")

    # Milvus settings
    milvus_host: str = Field(default="localhost", env="MILVUS_HOST")
    milvus_port: int = Field(default=19530, env="MILVUS_PORT")

    # MinIO settings
    minio_endpoint: str = Field(default="localhost:9000", env="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", env="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", env="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, env="MINIO_SECURE")

    # Execution runtime settings
    execution_sandbox_image: str = Field(default="kardcraft/sandbox:latest", env="EXECUTION_SANDBOX_IMAGE")
    execution_sandbox_runtime: str = Field(default="runsc", env="EXECUTION_SANDBOX_RUNTIME")
    execution_default_timeout_seconds: int = Field(default=60, env="EXECUTION_DEFAULT_TIMEOUT_SECONDS")
    execution_default_memory_mb: int = Field(default=512, env="EXECUTION_DEFAULT_MEMORY_MB")
    execution_monty_enabled: bool = Field(default=False, env="EXECUTION_MONTY_ENABLED")
    shell_execution_mode: Literal["auto", "sandbox", "local"] = Field(
        default="auto",
        env="SHELL_EXECUTION_MODE",
    )
    execution_auto_degrade_max_per_minute: int = Field(
        default=60,
        env="EXECUTION_AUTO_DEGRADE_MAX_PER_MINUTE",
    )

    # Sandbox broker control-plane config
    sandbox_broker_addr: str = Field(default="0.0.0.0:50061", env="SANDBOX_BROKER_ADDR")
    sandbox_broker_target: str = Field(default="sandbox-broker:50061", env="SANDBOX_BROKER_TARGET")
    sandbox_broker_timeout_seconds: float = Field(default=30.0, env="SANDBOX_BROKER_TIMEOUT_SECONDS")
    sandbox_broker_policy_file: str = Field(
        default="/app/config/policy-profiles.yaml",
        env="SANDBOX_BROKER_POLICY_FILE",
    )
    sandbox_broker_etcd_enabled: bool = Field(default=True, env="SANDBOX_BROKER_ETCD_ENABLED")
    sandbox_broker_etcd_endpoint: str = Field(
        default="http://etcd:2379",
        env="SANDBOX_BROKER_ETCD_ENDPOINT",
    )
    sandbox_broker_etcd_policy_key: str = Field(
        default="/kardcraft/sandbox-broker/policy-profiles",
        env="SANDBOX_BROKER_ETCD_POLICY_KEY",
    )
    sandbox_broker_max_concurrent_executions: int = Field(
        default=32,
        env="SANDBOX_BROKER_MAX_CONCURRENT_EXECUTIONS",
    )
    sandbox_broker_queue_wait_seconds: float = Field(
        default=3.0,
        env="SANDBOX_BROKER_QUEUE_WAIT_SECONDS",
    )
    sandbox_broker_policy_refresh_ttl_seconds: float = Field(
        default=2.0,
        env="SANDBOX_BROKER_POLICY_REFRESH_TTL_SECONDS",
    )

    # LLM settings
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")

    # Workflow settings
    workflow_timeout: int = Field(default=1800, env="WORKFLOW_TIMEOUT")  # 30 minutes
    checkpoint_enabled: bool = Field(default=True, env="CHECKPOINT_ENABLED")

    # Temporal settings
    temporal_endpoint: str = Field(default="temporal:7233", env="TEMPORAL_ENDPOINT")
    temporal_namespace: str = Field(default="default", env="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(default="agent-activities-queue", env="TEMPORAL_TASK_QUEUE")
    temporal_max_concurrent_activities: int = Field(default=100, env="TEMPORAL_MAX_CONCURRENT_ACTIVITIES")
    temporal_max_concurrent_workflow_tasks: int = Field(default=10, env="TEMPORAL_MAX_CONCURRENT_WORKFLOW_TASKS")
    temporal_max_worker_activities_per_second: float = Field(default=100.0, env="TEMPORAL_MAX_WORKER_ACTIVITIES_PER_SECOND")

    # Activity timeout settings
    activity_start_to_close_timeout: int = Field(default=1800, env="ACTIVITY_START_TO_CLOSE_TIMEOUT")
    activity_schedule_to_start_timeout: int = Field(default=300, env="ACTIVITY_SCHEDULE_TO_START_TIMEOUT")
    activity_heartbeat_timeout: int = Field(default=60, env="ACTIVITY_HEARTBEAT_TIMEOUT")

    # Workflow timeout settings
    workflow_execution_timeout: int = Field(default=3600, env="WORKFLOW_EXECUTION_TIMEOUT")
    workflow_run_timeout: int = Field(default=1800, env="WORKFLOW_RUN_TIMEOUT")
    workflow_task_timeout: int = Field(default=10, env="WORKFLOW_TASK_TIMEOUT")

    # Retry strategy
    temporal_max_attempts: int = Field(default=3, env="TEMPORAL_MAX_ATTEMPTS")
    temporal_initial_interval: int = Field(default=1, env="TEMPORAL_INITIAL_INTERVAL")
    temporal_backoff_coefficient: float = Field(default=2.0, env="TEMPORAL_BACKOFF_COEFFICIENT")
    temporal_maximum_interval: int = Field(default=100, env="TEMPORAL_MAXIMUM_INTERVAL")

    # Monitoring
    temporal_enable_metrics: bool = Field(default=True, env="TEMPORAL_ENABLE_METRICS")
    temporal_metrics_port: int = Field(default=9090, env="TEMPORAL_METRICS_PORT")

    # Checkpoint settings
    checkpoint_ttl_final: int = Field(default=86400, env="CHECKPOINT_TTL_FINAL")
    checkpoint_ttl_intermediate: int = Field(default=3600, env="CHECKPOINT_TTL_INTERMEDIATE")
    
class WorkspaceConfig(BaseModel):
    """Workspace-specific configuration."""
    
    user_id: str
    workspace_path: str
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB
    allowed_extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".py", ".js"])


class RedisConfig(BaseModel):
    """Redis-specific configuration."""
    
    url: str = "redis://localhost:6379"
    db: int = 0
    max_connections: int = 10
    retry_on_timeout: bool = True
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
