"""State definition for Intent Classifier Agent."""

from typing import TypedDict, List, Optional, Dict, Any


class State(TypedDict):
    """State for intent classification and routing."""

    # Input
    user_input: str
    file_ids: List[str]
    metadata: Dict[str, Any]

    # Classification results
    intent_type: Optional[str]  # 'create_cards', 'optimize_cards', 'review_cards', 'analyze_content'
    driven_mode: Optional[str]  # 'content_driven' | 'topic_driven' - determined by classifier
    subject_domain: Optional[str]  # 'mathematics', 'languages', 'sciences', etc.
    task_complexity: Optional[str]  # 'simple', 'medium', 'complex' - based on input scale
    language: Optional[str]  # Preferred card/output language (e.g., 'zh', 'en', 'ja')

    # Error handling
    classification_confidence: float
    error: Optional[str]
