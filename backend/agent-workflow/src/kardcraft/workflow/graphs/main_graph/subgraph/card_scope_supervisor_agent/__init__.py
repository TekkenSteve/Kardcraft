"""Card scope supervisor agent."""

from .builder import build_card_scope_supervisor_agent

card_scope_supervisor_agent = build_card_scope_supervisor_agent().compile()
