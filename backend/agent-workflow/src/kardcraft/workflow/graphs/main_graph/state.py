"""State for main graph thin orchestrator."""

from typing import Any, Dict, List, Optional, TypedDict
from dataclasses import dataclass, field

@dataclass(slots=True)
class Context:
    """Runtime context shared by graph execution."""

    user_id: str
    session_id: str
    workspace_id: str
    input_context: Dict[str, Any]
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    
class UserProfile(TypedDict, total=False):
    """Optional user-preference envelope."""

    difficulty_level: str
    preferred_language: Optional[str]
    learning_goals: List[str]
    metadata: Dict[str, Any]

class State(TypedDict, total=False):
    # Input
    user_input: str
    topic: Optional[str]
    message_knowledge: Optional[str]
    file_ids: List[str]
    target_count: int
    difficulty_level: str

    # Template context
    template_id: Optional[str]
    template_version: Optional[int]
    template_name: Optional[str]
    template_profiles: List[str]
    template_default_profile: Optional[str]
    selected_template_profile: Optional[str]
    template_note_fields: List[str]
    template_validation: Dict[str, Any]

    # Intent + global
    intent_type: Optional[str]
    driven_mode: Optional[str]
    subject_domain: Optional[str]
    task_complexity: Optional[str]
    language: Optional[str]

    # Stage statuses
    syllabus_status: Optional[str]       # outline_ready | need_user_input | failed
    evidence_status: Optional[str]       # evidence_ready | need_user_input | failed
    card_status: Optional[str]           # quality_pass | need_user_review | failed

    # Durable business outputs
    pending_questions: List[Dict[str, Any]]
    learning_units: List[Dict[str, Any]]
    approved_cards: List[Dict[str, Any]]
    final_cards: List[Dict[str, Any]]
    saved_card_ids: List[str]
    quality_report: Dict[str, Any]
    qa_loop_report: Dict[str, Any]

    # Observability + errors
    trace_id: Optional[str]
    error: Optional[str]
