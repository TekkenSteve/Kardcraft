"""Langfuse callbacks for DSPy tracing."""

from typing import Any, Dict, Optional

import dspy

from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.utils.logger import logger


class LangfuseCallback:
    """
    Callback handler for DSPy to Langfuse tracing.

    Features:
    - Automatic tracing of DSPy module executions
    - Prompt version tracking
    - Input/output capture
    - Error tracking
    """

    def __init__(self, trace_name: str = None):
        self.langfuse = get_langfuse_client()
        self.trace_name = trace_name or "dspy_execution"
        self._current_trace = None

    def __call__(self, module: dspy.Module, inputs: dict, output: Any):
        """
        Callback function for DSPy.

        Args:
            module: The DSPy module being executed
            inputs: Input arguments
            output: Output prediction
        """
        try:
            with self.langfuse.trace(name=self.trace_name) as trace:
                trace.update(
                    input=inputs,
                    metadata={
                        "module_type": type(module).__name__,
                        "module_name": getattr(module, "module_name", None),
                    },
                )

                if hasattr(output, "__dict__"):
                    trace.update(output=output.__dict__)
                else:
                    trace.update(output=str(output))

        except Exception as e:
            logger.warning(f"Langfuse callback error: {e}")

    def on_module_start(self, module: dspy.Module, inputs: dict):
        """Called when a module starts execution."""
        pass

    def on_module_end(self, module: dspy.Module, inputs: dict, output: Any):
        """Called when a module finishes execution."""
        self(module, inputs, output)

    def on_error(self, module: dspy.Module, inputs: dict, error: Exception):
        """Called when a module errors."""
        try:
            with self.langfuse.trace(name=self.trace_name) as trace:
                trace.update(
                    input=inputs,
                    metadata={
                        "error": str(error),
                        "module_type": type(module).__name__,
                    },
                )
        except Exception as e:
            logger.warning(f"Langfuse error callback failed: {e}")


class LangfuseTraceContext:
    """
    Context manager for manual Langfuse tracing.

    Usage:
        with LangfuseTraceContext("my_trace") as trace:
            result = module(input_data)
            trace.update(output=result)
    """

    def __init__(self, name: str = None, metadata: dict = None):
        self.name = name or "dspy_trace"
        self.metadata = metadata or {}
        self.langfuse = get_langfuse_client()
        self._trace = None

    def __enter__(self):
        self._trace = self.langfuse.trace(name=self.name)
        self._trace.update(metadata=self.metadata)
        return self._trace

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._trace:
            if exc_type:
                self._trace.update(
                    metadata={"error": str(exc_val), "error_type": exc_type.__name__}
                )
            self._trace.end()

    def update(self, **kwargs):
        """Update trace with additional data."""
        if self._trace:
            self._trace.update(**kwargs)


class DSPyObservation:
    """
    Wrapper for DSPy predictions with automatic Langfuse observation.

    Usage:
        obs = DSPyObservation(module, langfuse)
        result = obs(user_input="hello")
        # Automatically traced to Langfuse
    """

    def __init__(
        self, module: dspy.Module, langfuse_client=None, trace_name: str = None
    ):
        self.module = module
        self.langfuse = langfuse_client or get_langfuse_client()
        self.trace_name = trace_name or type(module).__name__

    def __call__(self, **kwargs) -> Any:
        """Execute module with automatic tracing."""
        with self.langfuse.trace(name=self.trace_name) as trace:
            trace.update(
                input=kwargs,
                metadata={"module": self.trace_name},
            )

            result = self.module(**kwargs)

            if hasattr(result, "__dict__"):
                trace.update(output=result.__dict__)
            else:
                trace.update(output=str(result))

            return result


def create_langfuse_observer(module: dspy.Module, trace_name: str = None):
    """
    Create a Langfuse observer wrapper for a DSPy module.

    Args:
        module: DSPy module to wrap
        trace_name: Name for the trace

    Returns:
        DSPyObservation wrapper
    """
    return DSPyObservation(module, trace_name=trace_name)


class PromptTracker:
    """
    Tracks prompt versions and changes for DSPy modules.

    Useful for understanding how prompts evolve during optimization.
    """

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.langfuse = get_langfuse_client()
        self._history: list[dict] = []

    def record_prompt(self, prompt: str, metadata: dict = None):
        """
        Record a prompt version.

        Args:
            prompt: Prompt content
            metadata: Additional metadata
        """
        entry = {
            "prompt": prompt,
            "metadata": metadata or {},
        }
        self._history.append(entry)

    def get_prompt_history(self) -> list[dict]:
        """Get recorded prompt history."""
        return self._history.copy()

    def publish_to_langfuse(
        self,
        labels: list[str] = None,
        config: dict = None,
    ) -> Optional[Any]:
        """
        Publish current prompt to Langfuse.

        Args:
            labels: Version labels
            config: Additional config

        Returns:
            Created prompt object
        """
        if not self._history:
            return None

        latest = self._history[-1]
        try:
            prompt_obj = self.langfuse.create_prompt(
                name=self.module_name,
                prompt=latest["prompt"],
                labels=labels or ["staging"],
                config=config or latest["metadata"],
            )
            return prompt_obj
        except Exception as e:
            logger.error(f"Failed to publish prompt to Langfuse: {e}")
            return None

    def get_langfuse_versions(self) -> list[dict]:
        """
        Get version history from Langfuse.

        Returns:
            List of version info
        """
        try:
            versions = self.langfuse.get_prompt_versions(self.module_name)
            return [
                {
                    "version": v.version,
                    "labels": v.labels,
                    "created_at": v.created_at,
                }
                for v in versions
            ]
        except Exception as e:
            logger.warning(f"Failed to get Langfuse versions: {e}")
            return []


_default_callback: Optional[LangfuseCallback] = None


def get_default_callback() -> LangfuseCallback:
    """Get the default Langfuse callback."""
    global _default_callback
    if _default_callback is None:
        _default_callback = LangfuseCallback()
    return _default_callback


def configure_dspy_tracing(enabled: bool = True, trace_name: str = "dspy"):
    """
    Configure DSPy global tracing with Langfuse.

    Note: DSPy doesn't have a built-in callback system in all versions,
    this provides a manual approach.

    Args:
        enabled: Whether to enable tracing
        trace_name: Base name for traces
    """
    if not enabled:
        return

    callback = LangfuseCallback(trace_name=trace_name)
    logger.info(f"DSPy Langfuse tracing enabled: {trace_name}")
    return callback
