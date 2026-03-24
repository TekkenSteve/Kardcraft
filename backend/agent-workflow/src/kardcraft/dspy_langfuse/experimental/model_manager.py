"""Multi-model support for DSPy + Langfuse."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import dspy

from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.utils.logger import logger


SUPPORTED_MODEL_FAMILIES = {"openai", "anthropic", "meta", "google"}


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    model_id: str
    family: str
    dspy_lm: dspy.LM
    temperature: float = 0.5
    max_tokens: int = 1024
    prompt_style: str = "neutral"


class ModelRegistry:
    """Registry for managing multiple model configurations."""

    def __init__(self):
        self.models: Dict[str, ModelConfig] = {}
        self._default_model: Optional[str] = None

    def register(
        self,
        model_id: str,
        family: str,
        dspy_lm: dspy.LM,
        temperature: float = 0.5,
        max_tokens: int = 1024,
        prompt_style: str = "neutral",
    ):
        """Register a model configuration."""
        self.models[model_id] = ModelConfig(
            model_id=model_id,
            family=family,
            dspy_lm=dspy_lm,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_style=prompt_style,
        )
        if self._default_model is None:
            self._default_model = model_id

    def get(self, model_id: str) -> Optional[ModelConfig]:
        """Get model configuration."""
        return self.models.get(model_id)

    def get_default(self) -> Optional[ModelConfig]:
        """Get default model."""
        if self._default_model:
            return self.models.get(self._default_model)
        return None

    def list_models(self) -> list[str]:
        """List all registered model IDs."""
        return list(self.models.keys())


class MultiModelPromptManager:
    """
    Manages prompts for multiple models with language support.

    Naming convention: {task}_{language}_{model_family}
    """

    def __init__(self, version_manager=None):
        self.langfuse = get_langfuse_client()
        self.version_manager = version_manager
        self.models = ModelRegistry()

    def get_prompt_name(
        self,
        task: str,
        language: str,
        model_id: str,
    ) -> str:
        """Generate prompt name with model family."""
        config = self.models.get(model_id)
        family = config.family if config else "openai"
        return f"{task}_{language}_{family}"

    def get_prompt(
        self,
        task: str,
        language: str,
        model_id: str,
        fallback_models: list[str] = None,
    ) -> Optional[str]:
        """
        Get prompt for a specific model with fallback.

        Args:
            task: Task name
            language: Language code (en, zh)
            model_id: Model ID
            fallback_models: Fallback model IDs to try

        Returns:
            Prompt content or None
        """
        prompt_name = self.get_prompt_name(task, language, model_id)

        try:
            prompt = self.langfuse.get_prompt(prompt_name, label="production")
            return prompt.prompt if prompt else None
        except Exception:
            pass

        if fallback_models:
            for fallback_id in fallback_models:
                try:
                    fallback_name = self.get_prompt_name(task, language, fallback_id)
                    prompt = self.langfuse.get_prompt(fallback_name, label="production")
                    if prompt:
                        logger.info(
                            f"Using fallback prompt: {model_id} -> {fallback_id}"
                        )
                        return prompt.prompt
                except Exception:
                    continue

        return None

    def publish_prompt(
        self,
        task: str,
        language: str,
        model_id: str,
        prompt: str,
        metric_score: float,
        labels: list[str] = None,
    ) -> Optional[Any]:
        """Publish prompt for a specific model."""
        prompt_name = self.get_prompt_name(task, language, model_id)
        labels = labels or ["staging"]

        config = self.models.get(model_id)
        model_family = config.family if config else "unknown"

        try:
            prompt_obj = self.langfuse.create_prompt(
                name=prompt_name,
                prompt=prompt,
                labels=labels,
                config={
                    "model_id": model_id,
                    "model_family": model_family,
                    "language": language,
                    "score": metric_score,
                },
            )
            logger.info(f"Published prompt: {prompt_name} (score: {metric_score:.3f})")
            return prompt_obj
        except Exception as e:
            logger.error(f"Failed to publish prompt: {e}")
            return None


_default_registry: Optional[ModelRegistry] = None
_default_manager: Optional[MultiModelPromptManager] = None


def get_model_registry() -> ModelRegistry:
    """Get the default model registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelRegistry()
    return _default_registry


def get_multi_model_manager() -> MultiModelPromptManager:
    """Get the default multi-model prompt manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = MultiModelPromptManager()
    return _default_manager
