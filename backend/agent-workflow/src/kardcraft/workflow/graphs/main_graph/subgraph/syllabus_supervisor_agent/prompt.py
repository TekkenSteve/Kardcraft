"""Prompt resolution for syllabus supervisor."""

from kardcraft.dspy_langfuse import PromptResolver

PROMPT_SCHEMA_VERSION = "1.0"
DEFAULT_PROMPT = (
    "You are a syllabus supervisor. Generate or refine learning units until outline is usable for card generation. "
    "If critical information is missing, request clarification."
)


def resolve_prompt(language: str | None = None) -> str:
    lang = (language or "en").strip() or "en"
    resolver = PromptResolver(prompt_label="production")
    resolved = resolver.resolve(
        module_name="syllabus_supervisor",
        lang=lang,
        local_default_prompt=DEFAULT_PROMPT,
        expected_schema_version=PROMPT_SCHEMA_VERSION,
    )
    return resolved.text

