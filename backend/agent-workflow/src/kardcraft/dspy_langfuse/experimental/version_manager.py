"""Prompt version management with Langfuse integration."""

import os
from datetime import datetime
from typing import Any, Optional
from difflib import SequenceMatcher

import dspy
from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.utils.logger import logger


class PromptVersionManager:
    """
    Manages DSPy prompt versions with Langfuse.

    Features:
    - Smart version creation (only when significantly improved)
    - Label-based environment management (staging/production)
    - Version history and rollback support
    - Multi-language prompt support
    """

    DEFAULT_THRESHOLD = 0.05

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.langfuse = get_langfuse_client()
        self.threshold = threshold

    def should_create_version(
        self,
        module_name: str,
        new_prompt: str,
        metric_score: float,
    ) -> tuple[bool, str]:
        """
        Decide whether to create a new version based on improvement.

        Args:
            module_name: Name of the prompt module
            new_prompt: The new prompt content
            metric_score: New evaluation score

        Returns:
            (should_create, reason)
        """
        try:
            current = self.langfuse.get_prompt(module_name, label="production")
            current_prompt = current.prompt if current else ""
            current_score = current.config.get("score", 0) if current else 0

            if not current_prompt:
                return True, "First version creation"

            if self._prompt_similarity(current_prompt, new_prompt) > 0.95:
                return False, "Prompt has no substantial change"

            if current_score > 0 and metric_score < current_score * (
                1 + self.threshold
            ):
                return (
                    False,
                    f"Metric improvement below {self.threshold * 100}% threshold",
                )

            return True, "Passed version creation check"

        except Exception as e:
            return True, f"First version: {e}"

    def publish_prompt(
        self,
        module_name: str,
        prompt: str,
        metric_score: float,
        labels: list[str] = None,
        config: dict = None,
        optimizer_type: str = "manual",
    ) -> Optional[Any]:
        """
        Publish a prompt version with smart version control.

        Args:
            module_name: Name of the prompt module
            prompt: Prompt content
            metric_score: Evaluation score
            labels: Labels for the version (default: ["staging"])
            config: Additional config to store
            optimizer_type: Type of optimizer used

        Returns:
            Created prompt object or None if skipped
        """
        should_create, reason = self.should_create_version(
            module_name, prompt, metric_score
        )

        if not should_create:
            logger.info(f"Skipping version creation for {module_name}: {reason}")
            return None

        labels = labels or ["staging"]
        config = config or {}
        config.update(
            {
                "score": metric_score,
                "optimizer": optimizer_type,
                "published_at": datetime.now().isoformat(),
                "dspy_version": dspy.__version__,
            }
        )

        try:
            prompt_obj = self.langfuse.create_prompt(
                name=module_name,
                prompt=prompt,
                labels=labels,
                config=config,
            )
            logger.info(
                f"Created new version for {module_name}, score: {metric_score:.3f}"
            )
            return prompt_obj
        except Exception as e:
            logger.error(f"Failed to create prompt version: {e}")
            return None

    def promote_to_production(
        self,
        module_name: str,
        version: Optional[int] = None,
    ) -> bool:
        """
        Promote a version to production.

        Args:
            module_name: Name of the prompt module
            version: Specific version to promote, or None for latest staging

        Returns:
            True if successful
        """
        try:
            if version:
                prompt = self.langfuse.get_prompt(module_name, version=version)
            else:
                prompt = self.langfuse.get_prompt(module_name, label="staging")

            self.langfuse.create_prompt(
                name=module_name,
                prompt=prompt.prompt,
                labels=["production"],
                config=prompt.config,
            )
            logger.info(f"Promoted version {prompt.version} to production")
            return True
        except Exception as e:
            logger.error(f"Failed to promote to production: {e}")
            return False

    def get_production_prompt(self, module_name: str) -> Optional[str]:
        """
        Get the production prompt for a module.

        Args:
            module_name: Name of the prompt module

        Returns:
            Prompt content or None
        """
        try:
            prompt = self.langfuse.get_prompt(module_name, label="production")
            return prompt.prompt if prompt else None
        except Exception:
            return None

    def get_latest_prompt(self, module_name: str) -> Optional[str]:
        """
        Get the latest prompt version.

        Args:
            module_name: Name of the prompt module

        Returns:
            Prompt content or None
        """
        try:
            prompt = self.langfuse.get_prompt(module_name, label="latest")
            return prompt.prompt if prompt else None
        except Exception:
            return None

    def get_prompt_with_fallback(
        self,
        module_name: str,
        languages: list[str] = None,
    ) -> Optional[str]:
        """
        Get prompt with language and label fallback.

        Args:
            module_name: Base name of the prompt module
            languages: List of languages to try (e.g., ["zh", "en"])

        Returns:
            Prompt content or None
        """
        languages = languages or ["en"]

        for lang in languages:
            prompt_name = f"{module_name}_{lang}"
            try:
                prompt = self.langfuse.get_prompt(prompt_name, label="production")
                if prompt:
                    return prompt.prompt
            except Exception:
                continue

        return self.get_production_prompt(module_name)

    def _prompt_similarity(self, p1: str, p2: str) -> float:
        """Calculate similarity between two prompts."""
        return SequenceMatcher(None, p1, p2).ratio()


_default_version_manager: Optional[PromptVersionManager] = None


def get_version_manager() -> PromptVersionManager:
    """Get the default version manager instance."""
    global _default_version_manager
    if _default_version_manager is None:
        _default_version_manager = PromptVersionManager()
    return _default_version_manager
