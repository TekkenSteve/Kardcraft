"""Tools for deep research graph."""

from langchain_core.tools import tool

from kardcraft.tools.web_search_tools import quick_research


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Reflection helper in research loop.

    Args:
        reflection: What was found, what is missing, and next step.

    Returns:
        Acknowledge reflection.
    """
    return f"reflection_recorded: {reflection}"


def get_research_tools():
    return [quick_research, think_tool]

