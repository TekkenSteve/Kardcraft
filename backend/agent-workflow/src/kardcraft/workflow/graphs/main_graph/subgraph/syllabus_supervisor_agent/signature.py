"""DSPy signature contracts for syllabus supervisor."""

from __future__ import annotations

import dspy

PROMPT_NAME = "syllabus_outline_planning"
PROMPT_SCHEMA_VERSION = "1"

INSTRUCTIONS = {
    "en": (
        "You are an outline planner for flashcard generation. "
        "Primary output must be a hierarchical outline built from provided sources. "
        "Select only suitable content progressively (top-down to detail), guided by principles, and avoid irrelevant sections. "
        "For content-driven mode, prioritize file-grounded knowledge. "
        "For topic-driven mode, prioritize deep-research-grounded knowledge. "
        "Return strict JSON in field outline_json with shape: "
        '{"outline":[{"id":str,"title":str,"summary":str,"source_ids":[str],"children":[same]}]}.'
    ),
    "zh": (
        "你是用于制卡的知识大纲规划器。"
        "核心产物必须是分层大纲，且必须基于给定来源内容。"
        "按原则进行渐进式披露（先整体后局部），只选择合适内容，排除无关内容。"
        "内容驱动时优先文件内容证据；主题驱动时优先 deep research 证据。"
        "请在 outline_json 字段返回严格 JSON，结构为："
        '{"outline":[{"id":str,"title":str,"summary":str,"source_ids":[str],"children":[same]}]}。'
    ),
}


class _OutlinePlanningSignature(dspy.Signature):
    """Outline planning signature."""

    task = dspy.InputField(desc="User task/request text")
    driven_mode = dspy.InputField(desc="content_driven|topic_driven")
    source_kind = dspy.InputField(desc="pageindex|ragix_summary|deep_research")
    selection_rule = dspy.InputField(desc="Selection rule text")
    principles_text = dspy.InputField(desc="Selection principles text")
    sources_json = dspy.InputField(desc="Sources JSON string")

    outline_json = dspy.OutputField(
        desc=(
            "Strict JSON string with key outline. "
            "Format: {\"outline\":[{\"id\":...,\"title\":...,\"summary\":...,\"source_ids\":[...],\"children\":[...]}]}"
        )
    )
    reasoning_brief = dspy.OutputField(desc="One-sentence rationale for source selection")


def build_signature_with_prompt(prompt_text: str) -> type[dspy.Signature]:
    """Bind runtime prompt to signature instructions."""
    return _OutlinePlanningSignature.with_instructions(prompt_text)
