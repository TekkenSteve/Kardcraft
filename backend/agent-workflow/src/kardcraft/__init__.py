"""
Kardcraft Agent Workflow

AI工作流层，负责执行复杂的工作流和管理用户工作空间。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "1.0.0"
__all__ = [
    "WorkflowManager",
    "WorkflowStatus",
    "WorkflowResult",
    # "WorkspaceService",
    "RedisClient",
    # "LLMFactory",
    "ToolRegistry",
    "RAGAnythingAdapter",
    "WdocAdapter",
    "Config",
]


def __getattr__(name: str) -> Any:
    """Lazy exports to avoid heavy/fragile imports at package import time."""
    if name in {"WorkflowManager", "WorkflowStatus", "WorkflowResult"}:
        module = import_module("kardcraft.workflow.manager")
        return getattr(module, name)
    if name == "RedisClient":
        module = import_module("kardcraft.services.redis")
        return getattr(module, name)
    if name == "ToolRegistry":
        module = import_module("kardcraft.tools.tool_registry")
        return getattr(module, name)
    if name == "Config":
        module = import_module("kardcraft.config")
        return getattr(module, name)
    raise AttributeError(f"module 'kardcraft' has no attribute {name!r}")
