# implementations/context_extractors/llm_context_extractor.py
"""
LLM增强的上下文提取器

使用LLM智能识别最相关的上下文，提高多模态处理的准确性
"""

from typing import Dict, Any, Optional
from .lightrag_context_extractor import LightRAGContextExtractor
from ...protocols.context_extractors import ContextExtractionResult, DocumentStructure
from ...protocols.processors_bak import ContextConfig


class LLMEnhancedContextExtractor(LightRAGContextExtractor):
    """LLM增强的上下文提取器 - 智能识别相关上下文

    继承自 LightRAGContextExtractor，添加LLM智能分析功能
    """

    def __init__(self, config: ContextConfig):
        """初始化LLM增强提取器"""
        super().__init__(config)
        self.llm_client = None  # LLM客户端将在初始化时创建

    async def _do_initialize(self) -> bool:
        """初始化LLM客户端"""
        try:
            # 这里可以初始化LLM客户端
            # 实际实现中需要根据配置创建相应的模型客户端
            self.llm_client = await self._create_llm_client()
            return True
        except Exception as e:
            print(f"Failed to initialize LLMEnhancedContextExtractor: {e}")
            return False

    async def extract_context_for_element(
        self,
        document_structure: DocumentStructure,
        element_id: str,
        element_index: Optional[int] = None
    ) -> ContextExtractionResult:
        """为指定元素提取上下文（LLM增强版）"""
        # 先获取基础上下文
        base_result = await super().extract_context_for_element(
            document_structure, element_id, element_index
        )

        # 如果LLM客户端未初始化，返回基础结果
        if not self.llm_client:
            return base_result

        try:
            # 使用LLM识别最相关的部分
            enhanced_context = await self._enhance_with_llm(
                base_result.context_text,
                document_structure.elements[element_index or document_structure.element_index_map[element_id]]
            )

            return ContextExtractionResult(
                context_text=enhanced_context,
                surrounding_elements=base_result.surrounding_elements,
                start_idx=base_result.start_idx,
                end_idx=base_result.end_idx,
                metadata={**base_result.metadata, "enhanced": True, "llm_used": True}
            )

        except Exception as e:
            print(f"LLM enhancement failed, falling back to base context: {e}")
            # LLM增强失败时回退到基础上下文
            return base_result

    async def _create_llm_client(self):
        """创建LLM客户端

        实际实现中应根据配置创建相应的LLM客户端
        例如：OpenAI、Anthropic、本地模型等
        """
        # 这里返回模拟客户端
        # 实际实现需要根据配置初始化真实客户端
        return {"type": "mock_llm_client"}

    async def _enhance_with_llm(self, context_text: str, target_element: Dict[str, Any]) -> str:
        """使用LLM增强上下文

        Args:
            context_text: 基础上下文文本
            target_element: 目标元素信息

        Returns:
            增强后的上下文文本
        """
        # 构建LLM提示
        prompt = self._build_enhancement_prompt(context_text, target_element)

        try:
            # 调用LLM
            enhanced_text = await self._call_llm(prompt)

            # 验证和清理响应
            cleaned_text = self._clean_llm_response(enhanced_text)

            return cleaned_text

        except Exception as e:
            print(f"LLM call failed: {e}")
            # LLM调用失败时返回原始上下文
            return context_text

    def _build_enhancement_prompt(self, context_text: str, target_element: Dict[str, Any]) -> str:
        """构建LLM增强提示"""
        element_type = target_element.get("type", "unknown")
        element_content = target_element.get("content", "")[:500]  # 限制长度

        prompt = f"""你是一个专业的文档分析助手。请分析以下文档上下文，并提取与目标元素最相关的部分。

目标元素类型：{element_type}
目标元素内容（部分）：{element_content}

完整上下文：
{context_text}

请完成以下任务：
1. 识别上下文中与目标元素最相关的部分
2. 去除无关或冗余的信息
3. 保持上下文的连贯性和完整性
4. 如果上下文已经很相关，可以直接返回原样

输出要求：
- 只返回增强后的上下文文本，不要添加解释
- 保持原文的语言和风格
- 确保重要信息不丢失

增强后的上下文："""

        return prompt

    async def _call_llm(self, prompt: str) -> str:
        """调用LLM

        实际实现中应调用真实的LLM API
        """
        # 模拟LLM响应
        # 实际实现应使用真实的LLM调用
        return prompt.split("\n\n")[-1] if "\n\n" in prompt else prompt

    def _clean_llm_response(self, response: str) -> str:
        """清理LLM响应"""
        # 移除可能的思考过程标记
        import re
        cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        # 移除 JSON 标记（如果有）
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```", "", cleaned)

        # 移除多余空白
        cleaned = cleaned.strip()

        return cleaned if cleaned else response