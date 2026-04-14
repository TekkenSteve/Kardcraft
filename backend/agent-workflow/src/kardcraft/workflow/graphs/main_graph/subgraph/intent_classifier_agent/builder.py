"""Builder for Intent Classifier Agent."""

from langgraph.graph import StateGraph, END
from .state import State
from .nodes import classify_intent

def build_intent_classifier_agent():
    """Build the intent classifier agent graph."""
    
    builder = StateGraph(State)
    
    # Add nodes
    builder.add_node("classify", classify_intent)
    
    # Set entry point
    builder.set_entry_point("classify")
    
    # Add edges
    builder.add_edge("classify", END)
    
    return builder
