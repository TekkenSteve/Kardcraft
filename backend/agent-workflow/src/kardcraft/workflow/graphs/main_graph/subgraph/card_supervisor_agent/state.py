"""State for card supervisor agent."""

from typing import Any, Dict, List, Optional, TypedDict


class CardSupervisorState(TypedDict, total=False):
    user_input: str
    message_knowledge: Optional[str]
    subject_domain: Optional[str]
    learning_units: List[Dict[str, Any]]
    template_profiles: List[str]
    template_default_profile: Optional[str]
    selected_template_profile: Optional[str]
    file_ids: List[str]
    quality_threshold: float
    judge_score_threshold: int
    max_qa_iterations: int

    status: str
    reason: str
    approved_cards: List[Dict[str, Any]]
    quality_report: Dict[str, Any]
    qa_loop_report: Dict[str, Any]
