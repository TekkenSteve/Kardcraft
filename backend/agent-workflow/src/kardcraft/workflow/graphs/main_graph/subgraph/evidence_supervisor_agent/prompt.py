"""Prompt resolution for evidence supervisor."""

from kardcraft.dspy_langfuse import PromptResolver

PROMPT_SCHEMA_VERSION = "1.0"
DEFAULT_PROMPT = (
    "You are an evidence supervisor. Ensure learning units have enough evidence context. "
    "Prefer RAG evidence first, then deep research if needed; return concise readiness decision. "
    "Tool contract: query_ragix_evidence accepts ONLY {query, top_k, session_id, file_ids, user_id}; "
    "do not invent extra parameters. In particular, do not pass 'mode' to query_ragix_evidence. "
    "For final decision, output status in {evidence_ready, need_user_input, failed} with a short reason."
)


def resolve_prompt(language: str | None = None) -> str:
    lang = (language or "en").strip() or "en"
    resolver = PromptResolver(prompt_label="production")
    resolved = resolver.resolve(
        module_name="evidence_supervisor",
        lang=lang,
        local_default_prompt=DEFAULT_PROMPT,
        expected_schema_version=PROMPT_SCHEMA_VERSION,
    )
    return resolved.text
