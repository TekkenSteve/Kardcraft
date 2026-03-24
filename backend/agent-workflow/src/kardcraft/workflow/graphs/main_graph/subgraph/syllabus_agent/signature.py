"""Syllabus agent signatures and prompt metadata contracts."""

from functools import lru_cache

import dspy

PROMPT_SCHEMA_VERSION = "1"
PROMPT_NAMES = {
    "context_sufficiency": "syllabus_context_sufficiency",
    "outline_chunk_extraction": "syllabus_outline_chunk_extraction",
    "outline_merge": "syllabus_outline_merge",
    "syllabus_generation": "syllabus_generation",
}


class _ContextSufficiencySignature(dspy.Signature):
    """Judge whether current context is enough for high-quality syllabus generation."""

    user_input = dspy.InputField(desc="User input")
    subject_domain = dspy.InputField(desc="Subject domain")
    user_knowledge = dspy.InputField(desc="User provided knowledge/content")
    retrieved_context = dspy.InputField(desc="Retrieved context snippets")

    is_sufficient = dspy.OutputField(desc="Whether context is sufficient")
    reason = dspy.OutputField(desc="Short rationale")
    missing_aspects = dspy.OutputField(desc="Missing aspects list")
    retrieval_queries = dspy.OutputField(desc="Suggested retrieval queries")


class _OutlineChunkExtractionSignature(dspy.Signature):
    """Extract candidate learning units from one source chunk."""

    user_input = dspy.InputField(desc="User input")
    subject_domain = dspy.InputField(desc="Subject domain")
    complexity_level = dspy.InputField(desc="Desired complexity level")
    chunk_id = dspy.InputField(desc="Current chunk id")
    chunk_content = dspy.InputField(desc="Current chunk text")

    learning_units = dspy.OutputField(desc="Extracted learning units")


class _OutlineMergeSignature(dspy.Signature):
    """Merge partial unit candidates into final coherent syllabus units."""

    user_input = dspy.InputField(desc="User input")
    subject_domain = dspy.InputField(desc="Subject domain")
    complexity_level = dspy.InputField(desc="Desired complexity level")
    partial_candidates_json = dspy.InputField(desc="Partial candidates JSON")

    learning_units = dspy.OutputField(desc="Final merged learning units")


class _SyllabusGenerationSignature(dspy.Signature):
    """Generate final syllabus units from overall source material in one pass."""

    user_input = dspy.InputField(desc="User input")
    subject_domain = dspy.InputField(desc="Subject domain")
    complexity_level = dspy.InputField(desc="Desired complexity level")
    source = dspy.InputField(desc="Source material")

    learning_units = dspy.OutputField(desc="Generated learning units")


@lru_cache(maxsize=32)
def build_context_sufficiency_signature(prompt_text: str) -> type[dspy.Signature]:
    return _ContextSufficiencySignature.with_instructions(prompt_text)


@lru_cache(maxsize=32)
def build_outline_chunk_extraction_signature(prompt_text: str) -> type[dspy.Signature]:
    return _OutlineChunkExtractionSignature.with_instructions(prompt_text)


@lru_cache(maxsize=32)
def build_outline_merge_signature(prompt_text: str) -> type[dspy.Signature]:
    return _OutlineMergeSignature.with_instructions(prompt_text)


@lru_cache(maxsize=32)
def build_syllabus_generation_signature(prompt_text: str) -> type[dspy.Signature]:
    return _SyllabusGenerationSignature.with_instructions(prompt_text)
