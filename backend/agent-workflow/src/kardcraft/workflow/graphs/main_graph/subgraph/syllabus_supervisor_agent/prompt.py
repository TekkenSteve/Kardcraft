"""Prompt management for syllabus supervisor outline planning."""

from __future__ import annotations

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
    """Resolve runtime prompt from Langfuse first, then local defaults."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.resolver = PromptResolver(prompt_label="production")

    def resolve_outline_prompt(self) -> ResolvedPrompt:
        default_prompt = INSTRUCTIONS.get(self.lang, INSTRUCTIONS["en"])
        return self.resolver.resolve(
            module_name=PROMPT_NAME,
            lang=self.lang,
            local_default_prompt=default_prompt,
            expected_schema_version=PROMPT_SCHEMA_VERSION,
        )


class OutlinePlanningPrompt(dspy.Module):
    """DSPy module for outline planning with runtime prompt resolution."""

    def __init__(self, lang: str = "en"):
        super().__init__()
        self.prompt_manager = PromptManager(lang=lang)
        self.resolved_prompt = self.prompt_manager.resolve_outline_prompt()

        if USE_DSPY:
            signature = build_signature_with_prompt(self.resolved_prompt.text)
            self.plan = dspy.ChainOfThought(signature)
        else:
            self.plan = None

    def forward(
        self,
        *,
        task: str,
        driven_mode: str,
        source_kind: str,
        selection_rule: str,
        principles_text: str,
        sources_json: str,
    ):
        if not USE_DSPY or self.plan is None:
            raise RuntimeError("DSPY_ENABLED=false, use LLM fallback path")
        return self.plan(
            task=task,
            driven_mode=driven_mode,
            source_kind=source_kind,
            selection_rule=selection_rule,
            principles_text=principles_text,
            sources_json=sources_json,
        )


def build_content_driven_summary_query(user_input: str) -> str:
    return f"请基于文件内容总结可用于制卡的大纲要点：{user_input}"
