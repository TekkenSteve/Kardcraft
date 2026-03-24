"""
Workflow-specific exceptions.
"""


class WorkflowError(Exception):
    """Base workflow exception."""
    pass


class WorkflowExecutionError(WorkflowError):
    """Workflow execution failed."""
    pass


class WorkflowTimeoutError(WorkflowError):
    """Workflow execution timeout."""
    pass


class WorkflowNotFoundError(WorkflowError):
    """Workflow or checkpoint not found."""
    pass


class WorkflowConfigurationError(WorkflowError):
    """Workflow configuration error."""
    pass