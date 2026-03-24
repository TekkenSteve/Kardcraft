# implementations/refiners/__init__.py - 精炼器实现模块
"""
精炼器组件实现

负责答案生成和精炼
"""

from .wdoc import WDocRefiner
from .simple import SimpleRefiner

__all__ = [
    "WDocRefiner",
    "SimpleRefiner",
]