"""State for main graph thin orchestrator."""

from typing import Any, Dict, List, Optional, TypedDict
from dataclasses import dataclass, field

EVIDENCE_STORE_SCHEMA_VERSION = "1"

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


class EvidenceItem(TypedDict, total=False):
    query: str
    content: str
    refs: List[Dict[str, Any]]
    node: Dict[str, Any] | None
    information_gain: float
    reason_codes: List[str]


class EvidenceStore(TypedDict, total=False):
    schema_version: str
    items: List[EvidenceItem]
    index: Dict[str, str]
    reason_code_counts: Dict[str, int]
    duplicate_query_ratio: float
    hit_rate: float


class CoverageState(TypedDict, total=False):
    coverage_rate: float
    covered_node_ids: List[str]
    total_node_count: int

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
    profile_prompt_hint: Dict[str, Any]

    # Intent + global
    intent_type: Optional[str]
    driven_mode: Optional[str]
    subject_domain: Optional[str]
    task_complexity: Optional[str]
    language: Optional[str]
    classification_confidence: Optional[float]
    query_scope: Optional[str]          # title_only | focused | full_doc
    preflight_status: Optional[str]     # pass_through | need_user_input | skipped
    preflight_reason: Optional[str]
    status: Optional[str]               # success | need_user_input | failed
    message: Optional[str]
    question: Optional[str]
    clarification_state: Optional[str]  # collecting | resolved | exhausted
    termination_reason: Optional[str]
    clarification_round: Optional[int]
    max_rounds: Optional[int]
    clarification_responses: Dict[str, str]
    asked_questions: List[str]

    # Stage statuses
    syllabus_status: Optional[str]       # outline_ready | need_user_input | failed
    evidence_status: Optional[str]       # evidence_ready | need_user_input | failed
    card_status: Optional[str]           # quality_pass | need_user_review | failed
    card_scope_status: Optional[str]     # scope_ready | need_user_input | failed

    # Durable business outputs
    file_tree_path_active: Optional[bool]
    retrieval_budget: Dict[str, Any]
    document_tree_status: Optional[str]
    document_tree_error: Optional[str]
    document_trees: List[Dict[str, Any]]
    tree_registry: Dict[str, Dict[str, Any]]
    candidate_nodes: List[Dict[str, Any]]
    scoped_learning_units: List[Dict[str, Any]]
    scope_chunks: List[Dict[str, Any]]
    selected_nodes: List[Dict[str, Any]]
    evidence_items: List[EvidenceItem]
    evidence_store: EvidenceStore
    coverage_state: CoverageState
    evidence_loop_report: Dict[str, Any]
    evidence_retry_count: Optional[int]
    pending_questions: List[Dict[str, Any]]
    learning_units: List[Dict[str, Any]]
    syllabus_outline: List[Dict[str, Any]]
    outline_sources: List[Dict[str, Any]]
    approved_cards: List[Dict[str, Any]]
    final_cards: List[Dict[str, Any]]
    saved_card_ids: List[str]
    quality_report: Dict[str, Any]
    qa_loop_report: Dict[str, Any]
    card_scope_report: Dict[str, Any]
    evidence_skillrouter_rollout: Dict[str, Any]

    # Observability + errors
    trace_id: Optional[str]
    error: Optional[str]
