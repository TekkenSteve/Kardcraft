# """Edge functions for Intent Classifier Agent."""

# from .state import IntentClassifierState

# def should_proceed_to_routing(state: IntentClassifierState) -> str:
#     """Determine if we should proceed to agent routing."""
    
#     # Check if classification was successful
#     if state.get("error"):
#         return "end"
    
#     # Check if we have valid intent type
#     intent_type = state.get("intent_type")
#     if not intent_type:
#         return "end"
    
#     return "route"

# def route_based_on_confidence(state: IntentClassifierState) -> str:
#     """Route based on classification confidence."""
    
#     confidence = state.get("classification_confidence", 0.0)
    
#     if confidence < 0.5:
#         return "low_confidence"
#     elif confidence < 0.8:
#         return "medium_confidence"
#     else:
#         return "high_confidence"