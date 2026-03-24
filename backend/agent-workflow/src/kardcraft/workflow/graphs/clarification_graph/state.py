"""State for clarification graph."""

from typing import Any, Dict, List, Optional, TypedDict


class ClarificationGraphState(TypedDict, total=False):
    user_input: str
    source_content: Optional[str]
    file_ids: List[str]
    language: Optional[str]
    pending_questions: List[Dict[str, Any]]

    status: str
    reason: str
    missing_info: List[str]

