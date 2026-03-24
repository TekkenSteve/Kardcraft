"""Base DSPy module with Langfuse integration."""

import os
from typing import Any, Callable, Optional, Type

import dspy

from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.utils.logger import logger
from .version_manager import PromptVersionManager, get_version_manager


class BasePromptModule(dspy.Module):
    """
    Base class for DSPy modules with Langfuse integration.

    Features:
    - Automatic prompt loading from Langfuse with fallback
    - Langfuse trace integration
    - Reusable across multiple agents
    - Multilingual support
    """

    DEFAULT_LANG = "en"
    DEFAULT_SIGNATURE: Type[dspy.Signature] = None

    def __init__(
        self,
        lang: str = None,
        signature: Type[dspy.Signature] = None,
        use_langfuse: bool = None,
        module_name: str = None,
    ):
        super().__init__()
        self.lang = lang or self.DEFAULT_LANG
        self.signature = signature or self.DEFAULT_SIGNATURE
        self.use_langfuse = (
            use_langfuse
            if use_langfuse is not None
            else os.getenv("DSPY_LANGFUSE_ENABLED", "true").lower() == "true"
        )
        self.module_name = module_name or self.__class__.__name__
        self.langfuse = get_langfuse_client()
        self.version_manager = get_version_manager() if self.use_langfuse else None

        self._prompt: Optional[str] = None
        self._initialized = False

    def _ensure_initialized(self):
        """Initialize the internal predictor if not already done."""
        if not self._initialized:
            if self.signature:
                prompt = self._load_prompt()
                if prompt:
                    self.signature = self.signature.with_instructions(prompt)
                self.predictor = dspy.ChainOfThought(self.signature)
            self._initialized = True

    def _load_prompt(self) -> Optional[str]:
        """Load prompt from Langfuse or return None for DSPy auto-generation."""
        if not self.use_langfuse:
            return None

        try:
            prompt = self.version_manager.get_prompt_with_fallback(
                self.module_name,
                languages=[self.lang, "en"],
            )
            if prompt:
                logger.debug(f"Loaded prompt for {self.module_name} from Langfuse")
            return prompt
        except Exception as e:
            logger.warning(f"Failed to load prompt from Langfuse: {e}")
            return None

    def forward(self, *args, **kwargs) -> dspy.Prediction:
        """Execute the module with Langfuse tracing."""
        self._ensure_initialized()

        if not self.use_langfuse or not hasattr(self, "predictor"):
            return self._forward_fallback(*args, **kwargs)

        with self.langfuse.trace(name=self.module_name) as trace:
            trace.update(
                input={"args": args, "kwargs": kwargs},
                metadata={"lang": self.lang},
            )

            result = self.predictor(*args, **kwargs)

            trace.update(output=result)

            return result

    def _forward_fallback(self, *args, **kwargs) -> Any:
        """Fallback for when DSPy is disabled."""
        raise NotImplementedError(
            f"Module {self.module_name} does not support fallback mode"
        )

    def get_prompt(self) -> str:
        """Get the current prompt (from Langfuse or signature)."""
        if self._prompt:
            return self._prompt
        if self.signature:
            return self.signature.__doc__ or ""
        return ""

    def set_prompt(self, prompt: str):
        """Set a custom prompt for the signature."""
        self._prompt = prompt
        if self.signature:
            self.signature = self.signature.with_instructions(prompt)
            self._initialized = False

    def publish_version(
        self,
        prompt: str,
        metric_score: float,
        labels: list[str] = None,
        config: dict = None,
    ) -> Optional[Any]:
        """
        Publish current state as a new version to Langfuse.

        Args:
            prompt: The prompt content to publish
            metric_score: Evaluation score
            labels: Version labels
            config: Additional config

        Returns:
            Created prompt object or None
        """
        if not self.use_langfuse:
            logger.warning("Langfuse not enabled, skipping version publish")
            return None

        return self.version_manager.publish_prompt(
            module_name=self.module_name,
            prompt=prompt,
            metric_score=metric_score,
            labels=labels,
            config=config,
        )


def create_prompt_module(
    signature: Type[dspy.Signature],
    module_name: str,
    lang: str = "en",
) -> Type[BasePromptModule]:
    """
    Factory function to create a prompt module class.

    Args:
        signature: DSPy Signature class
        module_name: Unique name for Langfuse prompt management
        lang: Default language

    Returns:
        A BasePromptModule subclass
    """

    class _PromptModule(BasePromptModule):
        DEFAULT_SIGNATURE = signature

    _PromptModule.__name__ = module_name

    return _PromptModule


class MultiLanguagePromptModule(BasePromptModule):
    """
    Extended base module with explicit multilingual support.

    Automatically switches prompts based on detected language.
    """

    LANGUAGE_CONFIGS = {
        "zh": {"model": "default", "fallback": "en"},
        "en": {"model": "default", "fallback": None},
    }

    def __init__(
        self,
        lang: str = "en",
        signature: Type[dspy.Signature] = None,
        use_langfuse: bool = None,
        module_name: str = None,
    ):
        super().__init__(lang, signature, use_langfuse, module_name)
        self._language_modules: dict[str, BasePromptModule] = {}

    def switch_language(self, lang: str):
        """Switch to a different language."""
        self.lang = lang
        self._initialized = False

    def get_prompt_for_language(self, lang: str) -> Optional[str]:
        """Get prompt for a specific language."""
        if not self.use_langfuse:
            return None

        try:
            prompt_name = f"{self.module_name}_{lang}"
            return self.version_manager.get_production_prompt(prompt_name)
        except Exception:
            return None
