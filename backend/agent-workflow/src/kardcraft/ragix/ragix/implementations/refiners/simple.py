# implementations/refiners/simple.py - 简单精炼器实现
"""
简单精炼器实现

提供基础的答案生成功能
"""

from typing import List, Dict, Any, Optional

from ...protocols.refiners import Refiner, RefinerConfig
from ...protocols.component import BaseComponent
from ..._types import Answer, Ref


class SimpleRefiner(BaseComponent):
    """简单精炼器 - 基础答案生成"""
    
    def __init__(self, config: RefinerConfig):
        super().__init__(config)
        self.config: RefinerConfig = config
        
    async def _do_initialize(self) -> bool:
        """初始化"""
        return True
    
    async def refine(self, question: str, chunks: List[str]) -> Answer:
        """精炼答案"""
        if not chunks:
            return Answer(
                text="抱歉，没有找到相关信息来回答您的问题。",
                citations=[]
            )
        
        # 简单拼接所有文本块
        context = "\n\n".join(chunks[:5])  # 限制前5个块
        
        # 构建引用
        citations = []
        for i, chunk in enumerate(chunks[:5]):
            ref = Ref(
                text=chunk,
                metadata={"source": "simple_refiner", "index": i},
                score=1.0 - (i * 0.1)
            )
            citations.append(ref)
        
        # 生成简单答案
        answer_text = await self.generate_answer(question, context)
        
        return Answer(
            text=answer_text,
            citations=citations
        )
    
    async def refine_with_refs(self, question: str, refs: List[Ref]) -> Answer:
        """使用引用精炼答案"""
        chunks = [ref.text for ref in refs]
        return await self.refine(question, chunks)
    
    async def generate_answer(
        self, 
        question: str, 
        context: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成答案"""
        # 简单的模板回答
        return f"""
基于提供的信息，针对问题"{question}"的回答：

{context[:500]}...

（这是一个简化的回答，基于检索到的相关信息）
"""