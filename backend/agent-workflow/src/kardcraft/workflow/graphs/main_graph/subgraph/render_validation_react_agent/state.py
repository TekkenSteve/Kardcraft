"""State for render validation ReAct agent."""

from typing import Any, Dict, List, TypedDict


class State(TypedDict, total=False):
    cards: List[Dict[str, Any]]
    payload: Dict[str, Any]
    validated_cards: List[Dict[str, Any]]
    render_validation_report: Dict[str, Any]
