"""DSPy LM configuration built on top of llm.discovery."""

from typing import Optional

import dspy

from kardcraft.utils.logger import logger

from .discovery import get_model

_configured_lm: Optional[dspy.LM] = None


def configure_dspy_lm(force_reconfigure: bool = False) -> Optional[dspy.LM]:
    """Configure and cache DSPy LM using the discovery-based model selector."""
    global _configured_lm

    if _configured_lm is not None and not force_reconfigure:
        return _configured_lm

    model_name, _ = get_model(intent="agent", temperature=0.0)
    try:
        lm = dspy.LM(model_name)
        dspy.configure(lm=lm)
        _configured_lm = lm
        logger.info("Configured DSPy LM", model=model_name)
        return lm
    except Exception as e:
        logger.warning("Failed to configure DSPy LM", model=model_name, error=str(e))
        _configured_lm = None
        return None
