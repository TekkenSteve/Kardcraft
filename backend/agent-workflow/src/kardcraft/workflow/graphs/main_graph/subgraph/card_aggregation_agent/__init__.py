"""Card aggregation agent."""

from .builder import build_card_aggregation_agent

card_aggregation_agent = build_card_aggregation_agent().compile()
