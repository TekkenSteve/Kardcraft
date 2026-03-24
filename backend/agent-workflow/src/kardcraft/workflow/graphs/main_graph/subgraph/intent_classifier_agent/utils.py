"""Utility functions for Intent Classifier Agent."""

from typing import Dict, Any, List
from kardcraft.utils.logger import logger
from kardcraft.utils.language import (
    normalize_language,
)


def parse_dspy_classification_result(
    result, user_input: str, file_ids: List[str]
) -> Dict[str, Any]:
    """Parse DSPy classification result with fallback logic."""
    inferred_mode = _infer_content_mode(user_input, file_ids)
    try:
        # Extract classification from DSPy result
        model_language = normalize_language(getattr(result, "language", "")) or None
        model_driven_mode = getattr(result, "driven_mode", inferred_mode)
        # Respect product routing design:
        # - If heuristics say content-driven (files uploaded or enough message content), never downgrade to topic-driven.
        # - If heuristics say topic-driven, model output may still upgrade to content-driven.
        if inferred_mode == "content_driven":
            final_driven_mode = "content_driven"
        else:
            final_driven_mode = model_driven_mode or inferred_mode

        classification = {
            "intent_type": getattr(result, "intent_type", "create_cards"),
            "driven_mode": final_driven_mode,
            "subject_domain": getattr(result, "subject_domain", "general"),
            "task_complexity": getattr(result, "task_complexity", "medium"),
            "confidence": float(getattr(result, "confidence", 0.8)),
            "language": model_language or "zh",
        }
        return classification

    except Exception as e:
        logger.warning("DSPy结果解析失败，使用默认分类", error=str(e))
        return {
            "intent_type": "create_cards",
            "driven_mode": inferred_mode,
            "subject_domain": "general",
            "task_complexity": "medium",
            "confidence": 0.6,
            "language": "zh",
        }


def _infer_content_mode(user_input: str, file_ids: List[str]) -> str:
    """Infer driven_mode from state - simple heuristic."""
    # Has uploaded files → content_driven
    if file_ids:
        return "content_driven"
    # Has actual text content in message → content_driven
    user_input = user_input or ""
    # TODO: 先简单判断, 后续再优化
    if user_input and len(user_input.strip()) > 50:
        return "content_driven"
    # Otherwise → topic_driven (just a topic/theme)
    return "topic_driven"


def prepare_file_info(file_ids: List[str]) -> str:
    """Prepare file information string for classification."""

    if file_ids:
        return f"User uploaded {len(file_ids)} files"
    return ""
