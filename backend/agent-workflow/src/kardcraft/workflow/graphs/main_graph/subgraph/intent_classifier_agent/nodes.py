"""Nodes for Intent Classifier Agent."""

from typing import Dict, Any
from kardcraft.utils.logger import logger
from kardcraft.services.langfuse import get_langfuse_client
from kardcraft.llm import configure_dspy_lm
from .state import State
from .prompt import IntentClassificationPrompt
from .utils import (
    parse_dspy_classification_result,
    prepare_file_info,
    _infer_content_mode,
)

langfuse = get_langfuse_client()


async def classify_intent(state: State) -> Dict[str, Any]:
    """Classify user intent and content characteristics."""

    logger.info(
        "🎯 Start Intent Classification",
        user_input_length=len(state["user_input"]),
        file_count=len(state.get("file_ids", [])),
    )

    try:
        lm = configure_dspy_lm()

        if lm is None:
            logger.warning("⚠️ Using fallback classification (no real LM configured)")
            classification = {
                "intent_type": "create_cards",
                "driven_mode": _infer_content_mode(
                    state.get("user_input"), state.get("file_ids")
                ),
                "subject_domain": "general",
                "task_complexity": "medium",
                "confidence": 0.5,
                "language": "zh",
            }
        else:
            file_info = prepare_file_info(state.get("file_ids", []))
            classifier = IntentClassificationPrompt()
            logger.debug("📝 Using DSPy IntentClassificationSignature")
            result = classifier.forward(
                user_input=state["user_input"], file_info=file_info
            )
            logger.info("🔍 DSPy raw result", result=str(result))
            classification = parse_dspy_classification_result(
                result, state.get("user_input", ""), state.get("file_ids", [])
            )

        logger.info(
            "✅ Intent classification completed",
            intent=classification["intent_type"],
            driven_mode=classification.get("driven_mode", ""),
            subject=classification["subject_domain"],
            confidence=classification["confidence"],
        )

        return classification

    except Exception as e:
        logger.error("❌Intent classification failed", error=str(e))
        return {
            "intent_type": "create_cards",
            "driven_mode": _infer_content_mode(
                state.get("user_input"), state.get("file_ids")
            ),
            "subject_domain": "general",
            "task_complexity": "medium",
            "confidence": 0.5,
            "language": "zh",
            "error": f"Classification failed: {str(e)}",
        }
