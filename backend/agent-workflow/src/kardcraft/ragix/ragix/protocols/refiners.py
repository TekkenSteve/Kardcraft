# protocols/refiners.py - 精炼器组件协议
"""
精炼器组件协议定义

负责答案生成和精炼
"""

from typing import Protocol, runtime_checkable, List, Dict, Any, Optional
from dataclasses import dataclass
from .component import Component, ComponentConfig
from .._types import Answer, Ref


@runtime_checkable
class Refiner(Component, Protocol):
    """精炼器协议"""
    
    async def refine(self, question: str, chunks: List[str]) -> Answer:
        """精炼答案"""
        ...
    
    async def refine_with_refs(self, question: str, refs: List[Ref]) -> Answer:
        """使用引用精炼答案"""
        ...
    
    async def generate_answer(
        self, 
        question: str, 
        context: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成答案"""
        ...


# 精炼器配置类
@dataclass
class RefinerConfig(ComponentConfig):
    """精炼器配置"""
    llm_model: str = "gpt-4o-mini"
    filter_model: Optional[str] = None  # 用于过滤的模型
    merge_model: Optional[str] = None   # 用于合并的模型
    max_context_length: int = 8000
    temperature: float = 0.1
    enable_citation: bool = True
    citation_format: str = "numbered"  # "numbered", "inline", "footnote"
    
    def __post_init__(self):
        if not hasattr(self, 'name') or not self.name:
            self.name = "refiner"
        if self.filter_model is None:
            self.filter_model = self.llm_model
        if self.merge_model is None:
            self.merge_model = self.llm_model
        super().__post_init__()