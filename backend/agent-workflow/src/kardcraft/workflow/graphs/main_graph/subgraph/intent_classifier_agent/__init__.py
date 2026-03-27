"""Intent Classifier Agent for routing user requests."""

from .builder import build_intent_classifier_agent

intent_classifier = build_intent_classifier_agent().compile()