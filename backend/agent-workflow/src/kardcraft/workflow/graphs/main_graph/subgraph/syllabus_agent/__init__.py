"""Syllabus Agent for generating knowledge dependency graphs."""

from .builder import build_syllabus_agent
# from .state import SyllabusState

# __all__ = [
#     "build_syllabus_agent",
#     "SyllabusState"
# ]
syllabus_agent = build_syllabus_agent().compile()