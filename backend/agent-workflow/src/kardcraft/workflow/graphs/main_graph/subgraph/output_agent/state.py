"""State for output agent."""

from typing import Any, Dict, List, TypedDict


class State(TypedDict, total=False):
    cards: List[Dict[str, Any]]
    payload: Dict[str, Any]
    output_cards: List[Dict[str, Any]]
