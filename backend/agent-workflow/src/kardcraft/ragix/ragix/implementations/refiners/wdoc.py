# implementations/refiners/wdoc.py - WDoc 精炼器实现
"""
WDoc 精炼器实现

使用真实的 LLM 进行答案生成
"""

import asyncio
from typing import List, Dict, Any, Optional, Callable

from ...protocols.refiners import Refiner, RefinerConfig
from ...protocols.component import BaseComponent
from ..._types import Answer, Ref
from kardcraft.utils.logger import logger


class WDocRefiner(BaseComponent):
    """WDoc 精炼器 - 智能答案精炼和引用管理"""

    def __init__(
        self,
        config: RefinerConfig,
        llm_func: Optional[Callable] = None,
    ):
        super().__init__(config)
        self.config: RefinerConfig = config
        self.llm_func = llm_func

    async def _do_initialize(self) -> bool:
        """初始化 LLM 函数"""
        try:
            # 如果没有提供 llm_func，尝试从配置创建
            if not self.llm_func:
                self.llm_func = await self._create_llm_func()

            if self.llm_func:
                logger.info("WDoc refiner initialized with LLM")
                return True

            logger.warning("No LLM function available, using fallback")
            return False

        except Exception as e:
            logger.error(f"Failed to initialize WDoc refiner: {e}")
            return False

    async def _create_llm_func(self) -> Optional[Callable]:
        """创建 LLM 调用函数"""
        try:
            # 尝试从 kardcraft.llm.factory 获取 LLM
            from kardcraft.llm.factory import get_llm

            llm = get_llm(
                model=self.config.llm_model or "gpt-4o-mini",
                temperature=0.3,
            )

            async def call_llm(prompt: str, system_prompt: str = "") -> str:
                response = await llm.ainvoke(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ]
                )
                return response.content

            return call_llm

        except ImportError:
            logger.warning("kardcraft.llm not available")
            return None
        except Exception as e:
            logger.error(f"Failed to create LLM function: {e}")
            return None

    async def refine(self, question: str, chunks: List[str]) -> Answer:
        """精炼答案"""
        if not chunks:
            return Answer(text="抱歉，没有找到相关信息来回答您的问题。", citations=[])

        try:
            # 构建上下文
            context = self._build_context(chunks)

            # 生成答案
            answer_text = await self.generate_answer(question, context)

            # 构建引用
            citations = self._build_citations(chunks)

            return Answer(text=answer_text, citations=citations)

        except Exception as e:
            logger.error(f"Answer refinement failed: {e}")
            return Answer(text=f"生成答案时出现错误: {e}", citations=[])

    async def refine_with_refs(self, question: str, refs: List[Ref]) -> Answer:
        """使用引用精炼答案"""
        if not refs:
            return Answer(text="抱歉，没有找到相关信息来回答您的问题。", citations=[])

        try:
            # 提取文本块
            chunks = [ref.text for ref in refs]

            # 构建上下文
            context = self._build_context(chunks)

            # 生成答案
            answer_text = await self.generate_answer(question, context)

            return Answer(text=answer_text, citations=refs)

        except Exception as e:
            logger.error(f"Answer refinement with refs failed: {e}")
            return Answer(text=f"生成答案时出现错误: {e}", citations=refs)

    async def generate_answer(
        self, question: str, context: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成答案"""
        try:
            # 构建提示
            prompt = self._build_prompt(question, context, metadata)

            # 调用 LLM
            if self.llm_func:
                answer = await self.llm_func(prompt)
                return answer
            else:
                # Fallback
                return self._fallback_answer(question, context)

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return f"生成答案时出现错误: {e}"

    def _fallback_answer(self, question: str, context: str) -> str:
        """备用答案生成"""
        # 简单的模板答案
        context_preview = context[:500] + "..." if len(context) > 500 else context
        return f"根据检索到的信息，我可以回答您的问题：\n\n关于「{question}」，相关内容如下：\n\n{context_preview}\n\n（这是基于上下文的简要回答）"

    def _build_context(self, chunks: List[str]) -> str:
        """构建上下文"""
        if not chunks:
            return ""

        # 限制上下文长度
        max_length = self.config.max_context_length
        context_parts = []
        current_length = 0

        for i, chunk in enumerate(chunks):
            chunk_length = len(chunk)

            if current_length + chunk_length > max_length:
                break

            # 添加引用编号
            if (
                self.config.enable_citation
                and self.config.citation_format == "numbered"
            ):
                context_parts.append(f"[{i + 1}] {chunk}")
            else:
                context_parts.append(chunk)

            current_length += chunk_length

        return "\n\n".join(context_parts)

    def _build_citations(self, chunks: List[str]) -> List[Ref]:
        """构建引用"""
        citations = []

        for i, chunk in enumerate(chunks):
            ref = Ref(
                text=chunk,
                metadata={"citation_id": i + 1, "source": "refined_context"},
                score=1.0 - (i * 0.1),  # 递减分数
            )
            citations.append(ref)

        return citations

    def _build_prompt(
        self, question: str, context: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建提示"""
        base_prompt = f"""请基于以下上下文信息回答问题。请确保答案准确、完整，并在适当的地方引用相关信息。

上下文信息：
{context}

问题：{question}

请提供详细的答案："""

        if self.config.enable_citation:
            if self.config.citation_format == "numbered":
                base_prompt += "\n注意：请在答案中使用 [数字] 的形式引用相关信息。"
            elif self.config.citation_format == "inline":
                base_prompt += "\n注意：请在答案中直接引用相关信息片段。"

        return base_prompt
