"""Standalone runner for Intent Classifier Agent."""

import asyncio
from .builder import build_intent_classifier_agent

async def main():
    """Test the intent classifier agent."""
    
    # Build the agent
    agent = build_intent_classifier_agent().compile()
    
    # Test cases
    test_cases = [
        {
            "user_input": "Help me make cards about calculus",
            "file_ids": [],
            "metadata": {}
        },
        {
            "user_input": "I uploaded some biology PDFs, please help me generate review cards.",
            "file_ids": ["file1.pdf", "file2.pdf"],
            "metadata": {"target_count": 20}
        },
        {
            "user_input": "Optimize my existing English vocabulary flashcards",
            "file_ids": [],
            "metadata": {"existing_cards": True}
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n=== Test Case {i} ===")
        print(f"Input: {test_case['user_input']}")
        
        try:
            result = await agent.ainvoke(test_case)
            print(f"Intent: {result.get('intent_type')}")
            print(f"Driven Mode: {result.get('driven_mode')}")
            print(f"Subject: {result.get('subject_domain')}")
            print(f"Complexity: {result.get('task_complexity')}")
            print(f"Confidence: {result.get('confidence')}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
