"""State definition for card_template_graph."""

from typing import TypedDict, Optional, Dict, Any, List


class CardTemplateState(TypedDict):
    """State for dedicated card template workflow."""

    user_id: Optional[str]
    session_id: str
    conversation_id: str
    topic: str
    file_ids: List[str]
    input: Dict[str, Any]

    template_id: Optional[str]
    template_version: Optional[int]
    render_target: Optional[str]

    template_bundle: Dict[str, Any]
    template_blueprint: Dict[str, Any]
    anki_payload: Dict[str, Any]
    output: Optional[str]
    status: Optional[str]
    error: Optional[str]
