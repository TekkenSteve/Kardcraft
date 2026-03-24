# protocols/__init__.py - 协议模块入口
"""
Ragix 协议定义模块

提供所有组件的协议接口，支持依赖注入和组合模式
"""

from .component import Component, ComponentConfig
from .processors_bak import DocumentProcessor, ModalProcessor
from .parsers import Parser, ParserDecorator
from .retrievers import Retriever, RetrieverStrategy
from .refiners import Refiner

__all__ = [
    # 基础组件协议
    "Component",
    "ComponentConfig",
    
    # 模型组件协议
    
    # 处理器组件协议
    "DocumentProcessor",
    "ModalProcessor",
    
    # 解析器组件协议
    "Parser",
    "ParserDecorator",
    
    # 检索器组件协议
    "Retriever",
    "RetrieverStrategy",
    
    # 精炼器组件协议
    "Refiner",
]
