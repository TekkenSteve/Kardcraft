# core/__init__.py - 核心模块入口
"""
Ragix 核心模块

提供依赖注入容器和组件注册表
"""

from .container import RagixContainer
from .registry import ComponentRegistry
__all__ = [
    "RagixContainer",
    "ComponentRegistry", 
]
