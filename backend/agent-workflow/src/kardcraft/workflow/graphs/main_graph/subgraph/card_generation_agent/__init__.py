"""Card generation agent."""

from .builder import build_card_generation_agent

card_generation_agent = build_card_generation_agent().compile()
