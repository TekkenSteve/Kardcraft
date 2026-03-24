"""State definition for Syllabus Agent.

Redesign based on docs/syllabus_agent_redesign_plan.md:
- Minimal, focused fields
- Integration with ragix via RagixClient.query()
- Tool-based calling for同级 agents (clarification_agent, deep_research_agent)
- file_ids passed from upstream (frontend upload to minio)
- session_id for workspace isolation
- user_id for file download
"""

from typing import TypedDict, List, Optional, Dict, Any


class LearningUnit(TypedDict):
    """Flexible learning unit - can be chapter, module, topic, or concept cluster.

    Redesigned with minimal fields per plan:
    - Removed: rag_context (not needed per unit)
    - Added: status (draft/approved/rejected)
    """

    id: str  # Unique identifier
    title: str  # Title
    content_summary: str  # LLM-generated summary
    key_concepts: List[str]  # Key concepts
    difficulty: Optional[str]  # Difficulty level (optional)
    estimated_time: Optional[int]  # Estimated time in minutes (optional)
    prerequisites: List[str]  # IDs of prerequisite units
    status: str  # "draft" | "approved" | "rejected"


class ClarificationQuestion(TypedDict):
    """Question to ask user for clarification."""

    question_id: str
    question_text: str
    options: Optional[List[str]]  # Multiple choice options if available
    context: Dict[str, Any]  # Context for the question


class SyllabusState(TypedDict):
    """State for syllabus generation with ragix integration.

    Redesigned per plan:
    - Input: user_input, user_knowledge, file_ids (from upstream), session_id, user_id, subject_domain, complexity_level, language
    - Ragix: rag_queries (history), retrieved_context
    - Output: syllabus_draft, learning_units, approved_unit_ids
    - Interaction: pending_questions, clarification_responses
    - Control: iteration_count, max_iterations, error
    """

    # ===== Input (from upstream intent_classifier) =====
    user_input: str  # User's request/question
    user_knowledge: str  # Prior knowledge from message content
    file_ids: Optional[List[str]]  # File IDs from frontend upload to minio
    session_id: Optional[str]  # Session ID for ragix workspace isolation
    user_id: Optional[str]  # User ID for file download
    subject_domain: Optional[str]  # Subject domain (optional)
    complexity_level: Optional[str]  # Complexity level (optional)
    language: Optional[str]  # Preferred language from intent_classifier

    # ===== Ragix Query History =====
    rag_queries: List[
        Dict[str, Any]
    ]  # Query history [{query, mode, result, timestamp}]
    retrieved_context: List[Dict[str, Any]]  # Current accumulated context

    # ===== Output =====
    syllabus_draft: str  # Raw LLM output (original)
    learning_units: List[LearningUnit]  # Parsed learning units
    approved_unit_ids: List[str]  # Approved unit IDs

    # ===== Interaction =====
    pending_questions: List[ClarificationQuestion]  # Questions awaiting user response
    clarification_responses: Dict[str, Any]  # User's responses
    user_feedback: Optional[str]  # Feedback on the draft syllabus
    
    # ===== Control Flow =====
    iteration_count: int  # Current iteration
    max_iterations: int  # Maximum iterations (default: 3)


    # ===== Error Handling =====
    error: Optional[str]
