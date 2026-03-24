"""Syllabus supervisor agent."""

from .builder import build_syllabus_supervisor_agent

syllabus_supervisor_agent = build_syllabus_supervisor_agent().compile()

__all__ = ["syllabus_supervisor_agent", "build_syllabus_supervisor_agent"]
