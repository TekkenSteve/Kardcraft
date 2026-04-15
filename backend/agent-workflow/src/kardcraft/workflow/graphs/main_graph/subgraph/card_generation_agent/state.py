"""State for card generation agent."""

from typing import Any, Dict, List, Optional, TypedDict


class State(TypedDict, total=False):
    chunk_id: str
    unit_ids: List[str]
    template_id: str
    template_version: int
    user_input: str
    message_knowledge: Optional[str]
    subject_domain: Optional[str]
    query_scope: Optional[str]
    learning_units: List[Dict[str, Any]]
    evidence_items: List[Dict[str, Any]]
    document_trees: List[Dict[str, Any]]
    template_profiles: List[str]
    template_default_profile: Optional[str]
    selected_template_profile: Optional[str]
    profile_prompt_hint: Dict[str, Any]
    file_ids: List[str]

    approved_cards: List[Dict[str, Any]]
    refined_cards: List[Dict[str, Any]]
    quality_report: Dict[str, Any]
    raw_cards: List[Dict[str, Any]]
    fatal_error: Optional[str]
