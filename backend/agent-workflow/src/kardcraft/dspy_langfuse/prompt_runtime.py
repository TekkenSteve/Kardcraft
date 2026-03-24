"""Runtime prompt resolution for DSPy modules with Langfuse fallback."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Optional

from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.utils.logger import logger


@dataclass(frozen=True)
class ResolvedPrompt:
    """Resolved prompt payload used by runtime modules."""

    text: str
    source: str
    prompt_name: str
    prompt_label: str
    prompt_version: str
    schema_version: str
    prompt_hash: str


class PromptResolver:
    """
    Resolve runtime prompt using Langfuse first, then local default.

    Resolution order:
    1. Langfuse prompt by label ("production" by default), language-specific name first.
    2. Local default prompt (always available fallback).
    """

    def __init__(
        self,
        *,
        prompt_label: str = "production",
        use_langfuse: Optional[bool] = None,
    ) -> None:
        self.langfuse = get_langfuse_client()
        self.prompt_label = prompt_label
        self.use_langfuse = (
            use_langfuse
            if use_langfuse is not None
            else os.getenv("DSPY_LANGFUSE_ENABLED", "true").lower() == "true"
        )

    def resolve(
        self,
        *,
        module_name: str,
        lang: str,
        local_default_prompt: str,
        expected_schema_version: str,
    ) -> ResolvedPrompt:
        """Resolve prompt and return full metadata for tracing."""
        prompt_names = [f"{module_name}_{lang}", module_name]

        if self.use_langfuse:
            for prompt_name in prompt_names:
                resolved = self._resolve_from_langfuse(
                    prompt_name=prompt_name,
                    expected_schema_version=expected_schema_version,
                )
                if resolved is not None:
                    return resolved

        return self._local_default(
            module_name=module_name,
            prompt_text=local_default_prompt,
            expected_schema_version=expected_schema_version,
        )

    def _resolve_from_langfuse(
        self,
        *,
        prompt_name: str,
        expected_schema_version: str,
    ) -> Optional[ResolvedPrompt]:
        try:
            prompt_obj = self.langfuse.get_prompt(prompt_name, label=self.prompt_label)
        except Exception as exc:
            logger.warning(
                "Langfuse prompt fetch failed",
                prompt_name=prompt_name,
                label=self.prompt_label,
                error=str(exc),
            )
            return None

        if not prompt_obj:
            return None

        prompt_text = getattr(prompt_obj, "prompt", "")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            logger.warning("Langfuse prompt is empty", prompt_name=prompt_name)
            return None

        config = getattr(prompt_obj, "config", {}) or {}
        runtime_schema_version = str(config.get("schema_version", "")).strip()
        if runtime_schema_version and runtime_schema_version != expected_schema_version:
            logger.warning(
                "Langfuse prompt schema mismatch; fallback to local",
                prompt_name=prompt_name,
                expected_schema_version=expected_schema_version,
                runtime_schema_version=runtime_schema_version,
            )
            return None

        prompt_version = str(getattr(prompt_obj, "version", "unknown"))
        return ResolvedPrompt(
            text=prompt_text,
            source="langfuse",
            prompt_name=prompt_name,
            prompt_label=self.prompt_label,
            prompt_version=prompt_version,
            schema_version=runtime_schema_version or expected_schema_version,
            prompt_hash=_hash_prompt(prompt_text),
        )

    def _local_default(
        self,
        *,
        module_name: str,
        prompt_text: str,
        expected_schema_version: str,
    ) -> ResolvedPrompt:
        return ResolvedPrompt(
            text=prompt_text,
            source="local_default",
            prompt_name=module_name,
            prompt_label="local",
            prompt_version="local-default",
            schema_version=expected_schema_version,
            prompt_hash=_hash_prompt(prompt_text),
        )


def _hash_prompt(prompt_text: str) -> str:
    """Create a stable short hash for trace and cache keys."""
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
