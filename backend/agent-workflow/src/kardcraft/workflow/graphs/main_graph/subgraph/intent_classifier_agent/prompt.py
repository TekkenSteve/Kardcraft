"""Prompt management for Intent Classifier Agent."""

import os

import dspy

from kardcraft.dspy_langfuse import PromptResolver, ResolvedPrompt
from .signature import (
    INSTRUCTIONS,
    PROMPT_NAME,
    PROMPT_SCHEMA_VERSION,
    build_signature_with_prompt,
)

USE_DSPY = os.getenv("DSPY_ENABLED", "true").lower() == "true"


class PromptManager:
    """Resolve runtime prompt using Langfuse first, then local defaults."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.resolver = PromptResolver(prompt_label="production")

    def resolve_classification_prompt(self) -> ResolvedPrompt:
        default_prompt = INSTRUCTIONS.get(self.lang, INSTRUCTIONS["en"])
        return self.resolver.resolve(
            module_name=PROMPT_NAME,
            lang=self.lang,
            local_default_prompt=default_prompt,
            expected_schema_version=PROMPT_SCHEMA_VERSION,
        )


class IntentClassificationPrompt(dspy.Module):
    """DSPy module for intent classification with runtime prompt resolution."""

    def __init__(self, lang: str = "en"):
        super().__init__()
        self.prompt_manager = PromptManager(lang=lang)
        self.resolved_prompt = self.prompt_manager.resolve_classification_prompt()

        if USE_DSPY:
            signature = build_signature_with_prompt(self.resolved_prompt.text)
            self.classify = dspy.ChainOfThought(signature)
        else:
            self.classify = None

    def forward(self, user_input: str, file_info: str = ""):
        """Classify user intent and content characteristics."""
        if not USE_DSPY:
            raise RuntimeError("DSPY_ENABLED=false, implement fallback logic")
        assert self.classify is not None, "Classification chain not initialized"
        return self.classify(user_input=user_input, file_info=file_info)
