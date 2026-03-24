# implementations/processors/modal.py - 多模态处理器实现
"""
多模态处理器组件实现

参考 RAGAnything 的 modalprocessors.py，组合实现
"""

import json
import base64
from typing import Dict, Any, List, Optional
from pathlib import Path

from ...protocols.processors_bak import ModalProcessor, ModalProcessorConfig, ModalItem, ProcessedModalItem
from ...protocols.component import BaseComponent


class BaseModalProcessor(BaseComponent):
    """多模态处理器基类 - 支持上下文感知处理"""

    def __init__(self, config: ModalProcessorConfig):
        super().__init__(config)
        self.config: ModalProcessorConfig = config
        self.llm_func = None
        self.vision_func = None
        self.context_extractor = None  # 上下文提取器实例
        
    async def _do_initialize(self) -> bool:
        """初始化处理器"""
        try:
            # 这里可以初始化 LLM 和视觉模型
            # 实际实现中需要根据配置创建相应的模型客户端
            return True
        except Exception as e:
            print(f"Failed to initialize modal processor: {e}")
            return False

    def set_context_extractor(self, extractor):
        """设置上下文提取器 - 依赖注入

        Args:
            extractor: ContextExtractor 实例
        """
        self.context_extractor = extractor

    def has_context_support(self) -> bool:
        """检查是否支持上下文处理"""
        return (self.context_extractor is not None and
                self.config.enable_context_extraction)

    async def process_with_context(self, item: ModalItem, document_structure) -> ProcessedModalItem:
        """带上下文的处理多模态项目

        Args:
            item: 多模态项目
            document_structure: 文档结构对象

        Returns:
            处理后的多模态项目
        """
        try:
            # 提取上下文
            context_result = await self._extract_context(item, document_structure)

            # 使用上下文增强描述生成
            enhanced_description, entity_info = await self.generate_description_with_context(
                item.content,
                item.content_type,
                item.item_info,
                context_result.context_text if context_result else None
            )

            # 构建结果
            return ProcessedModalItem(
                enhanced_description=enhanced_description,
                entity_info=entity_info,
                chunk_content=self._build_chunk_content_with_context(item, enhanced_description, context_result),
                original_item=item
            )

        except Exception as e:
            print(f"Context-aware processing failed, falling back to regular processing: {e}")
            # 回退到无上下文处理
            return await self.process(item)

    async def generate_description_with_context(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        context_text: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """使用上下文生成描述

        子类应重写此方法以实现具体的上下文感知处理
        默认实现忽略上下文，调用 generate_description_only
        """
        return await self.generate_description_only(
            modal_content, content_type, item_info, entity_name
        )

    async def process_batch(self, items: List[ModalItem]) -> List[ProcessedModalItem]:
        """两阶段批处理 - 参考 RAGAnything 的设计
        
        Stage 1: 并发生成所有描述
        Stage 2: 批量创建实体和块
        """
        import asyncio
        
        # Stage 1: 并发生成描述
        description_tasks = []
        for item in items:
            if self.has_context_support():
                # 使用上下文感知处理
                task = self.generate_description_with_context(
                    item.content, item.content_type, item.item_info
                )
            else:
                # 使用基础处理
                task = self.generate_description_only(
                    item.content, item.content_type, item.item_info
                )
            description_tasks.append(task)
        
        # 并发执行所有描述生成任务
        descriptions_and_entities = await asyncio.gather(*description_tasks, return_exceptions=True)
        
        # Stage 2: 批量创建实体和块
        processed_items = []
        for i, (item, desc_result) in enumerate(zip(items, descriptions_and_entities)):
            try:
                if isinstance(desc_result, Exception):
                    # 处理异常情况
                    print(f"Error processing item {i}: {desc_result}")
                    fallback_entity = {
                        "entity_name": f"{item.content_type}_{hash(str(item.content))}",
                        "entity_type": item.content_type,
                        "summary": f"Error processing {item.content_type}: {str(desc_result)[:100]}",
                    }
                    processed_item = ProcessedModalItem(
                        enhanced_description=str(item.content),
                        entity_info=fallback_entity,
                        chunk_content=str(item.content),
                        original_item=item
                    )
                else:
                    enhanced_description, entity_info = desc_result
                    chunk_content = self._build_chunk_content(item, enhanced_description)
                    
                    processed_item = ProcessedModalItem(
                        enhanced_description=enhanced_description,
                        entity_info=entity_info,
                        chunk_content=chunk_content,
                        original_item=item
                    )
                
                processed_items.append(processed_item)
                
            except Exception as e:
                print(f"Error creating processed item {i}: {e}")
                # 创建回退项目
                fallback_entity = {
                    "entity_name": f"{item.content_type}_{hash(str(item.content))}",
                    "entity_type": item.content_type,
                    "summary": f"Fallback {item.content_type}: {str(item.content)[:100]}",
                }
                processed_items.append(ProcessedModalItem(
                    enhanced_description=str(item.content),
                    entity_info=fallback_entity,
                    chunk_content=str(item.content),
                    original_item=item
                ))
        
        return processed_items

    def _build_chunk_content(self, item: ModalItem, enhanced_description: str) -> str:
        """构建块内容 - 基础版本"""
        return f"""
Content Type: {item.content_type.title()}
Content: {str(item.content)[:500]}
Enhanced Description: {enhanced_description}
"""

    async def _extract_context(self, item: ModalItem, document_structure):
        """提取上下文

        Args:
            item: 多模态项目
            document_structure: 文档结构对象

        Returns:
            ContextExtractionResult 或 None
        """
        if not self.has_context_support() or not item.item_info:
            return None

        try:
            from ...protocols.context_extractors import DocumentStructure as ContextDocumentStructure

            # 转换文档结构类型
            context_doc_structure = ContextDocumentStructure(
                elements=document_structure.elements,
                metadata=document_structure.metadata,
                element_index_map=document_structure.element_index_map
            )

            # 从 item_info 获取位置信息
            element_id = item.item_info.get("element_id")
            position = item.item_info.get("position")

            if element_id:
                return await self.context_extractor.extract_context_for_element(
                    context_doc_structure, element_id
                )
            elif position:
                return await self.context_extractor.extract_context_with_position(
                    context_doc_structure, position
                )

            return None

        except Exception as e:
            print(f"Failed to extract context: {e}")
            return None

    def _build_chunk_content_with_context(self, item: ModalItem, enhanced_description: str, context_result):
        """构建带上下文的块内容"""
        base_content = f"""
Content Type: {item.content_type.title()}
Content: {str(item.content)[:500]}
Enhanced Description: {enhanced_description}
"""

        if context_result and context_result.context_text:
            base_content += f"\nContext: {context_result.context_text[:1000]}"

        return base_content

    def get_supported_types(self) -> List[str]:
        """获取支持的内容类型"""
        return self.config.supported_types
    
    def supports_content_type(self, content_type: str) -> bool:
        """检查是否支持指定内容类型"""
        return content_type in self.get_supported_types()
    
    def _robust_json_parse(self, response: str) -> dict:
        """健壮的 JSON 解析 - 参考 RAGAnything 的四层 fallback 策略"""
        if not response or not response.strip():
            return self._get_fallback_result()
        
        # 策略1: 直接解析
        for json_candidate in self._extract_all_json_candidates(response):
            result = self._try_parse_json(json_candidate)
            if result:
                return result
        
        # 策略2: 基础清理后解析
        for json_candidate in self._extract_all_json_candidates(response):
            cleaned = self._basic_json_cleanup(json_candidate)
            result = self._try_parse_json(cleaned)
            if result:
                return result
        
        # 策略3: 渐进式引号修复
        for json_candidate in self._extract_all_json_candidates(response):
            fixed = self._progressive_quote_fix(json_candidate)
            result = self._try_parse_json(fixed)
            if result:
                return result
        
        # 策略4: 正则表达式字段提取（最后手段，保证不崩溃）
        return self._extract_fields_with_regex(response)
    
    def _extract_all_json_candidates(self, response: str) -> list:
        """提取所有可能的 JSON 候选 - 增强版"""
        import re
        candidates = []
        
        # 预处理：移除思考标签 - 针对 DeepSeek-R1、Qwen-2.5-think 等
        cleaned_response = re.sub(
            r"<think>.*?</think>", "", response, flags=re.DOTALL | re.IGNORECASE
        )
        cleaned_response = re.sub(
            r"<thinking>.*?</thinking>",
            "",
            cleaned_response,
            flags=re.DOTALL | re.IGNORECASE,
        )
        
        # 移除其他常见的非JSON标签
        cleaned_response = re.sub(
            r"<reasoning>.*?</reasoning>",
            "",
            cleaned_response,
            flags=re.DOTALL | re.IGNORECASE,
        )
        
        # 方法1: 代码块中的 JSON
        json_blocks = re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```", cleaned_response, re.DOTALL
        )
        candidates.extend(json_blocks)
        
        # 方法2: 平衡的大括号（改进版）
        brace_count = 0
        start_pos = -1
        
        for i, char in enumerate(cleaned_response):
            if char == "{":
                if brace_count == 0:
                    start_pos = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_pos != -1:
                    candidate = cleaned_response[start_pos : i + 1]
                    # 过滤明显不是JSON的候选
                    if self._is_likely_json(candidate):
                        candidates.append(candidate)
        
        # 方法3: 简单正则回退
        simple_match = re.search(r"\{[^{}]*\}", cleaned_response, re.DOTALL)
        if simple_match:
            candidates.append(simple_match.group(0))
        
        # 方法4: 多行JSON匹配
        multiline_match = re.search(
            r'\{\s*"[^"]+"\s*:\s*"[^"]*"(?:\s*,\s*"[^"]+"\s*:\s*[^}]+)*\s*\}',
            cleaned_response,
            re.DOTALL
        )
        if multiline_match:
            candidates.append(multiline_match.group(0))
        
        return candidates
    
    def _is_likely_json(self, candidate: str) -> bool:
        """判断候选字符串是否可能是JSON"""
        if not candidate or len(candidate) < 2:
            return False
        
        # 基本结构检查
        if not (candidate.strip().startswith('{') and candidate.strip().endswith('}')):
            return False
        
        # 检查是否包含引号对
        quote_count = candidate.count('"')
        if quote_count < 2:  # 至少需要一个键值对
            return False
        
        # 检查是否包含冒号
        if ':' not in candidate:
            return False
        
        return True
    
    def _try_parse_json(self, json_str: str) -> dict:
        """尝试解析 JSON 字符串 - 增强版"""
        if not json_str or not json_str.strip():
            return None
        
        try:
            result = json.loads(json_str)
            # 验证结果是字典且包含必要字段
            if isinstance(result, dict) and self._validate_json_result(result):
                return result
            return None
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
    
    def _validate_json_result(self, result: dict) -> bool:
        """验证JSON解析结果是否包含必要字段"""
        # 检查是否包含描述相关字段
        description_fields = ["detailed_description", "description", "summary"]
        has_description = any(field in result for field in description_fields)
        
        # 检查是否包含实体信息
        has_entity_info = "entity_info" in result or "entity_name" in result
        
        return has_description or has_entity_info
    
    def _basic_json_cleanup(self, json_str: str) -> str:
        """基础 JSON 清理 - 增强版"""
        import re
        
        # 移除多余空白
        json_str = json_str.strip()
        
        # 修复智能引号
        json_str = json_str.replace('"', '"').replace('"', '"')
        json_str = json_str.replace(""", '"').replace(""", '"')
        json_str = json_str.replace("'", "'").replace("'", "'")
        
        # 修复单引号为双引号（JSON标准）
        json_str = re.sub(r"'([^']*)':", r'"\1":', json_str)  # 键
        json_str = re.sub(r":\s*'([^']*)'", r': "\1"', json_str)  # 值
        
        # 修复尾随逗号
        json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
        
        # 修复缺失的逗号
        json_str = re.sub(r'"\s*\n\s*"', '",\n"', json_str)
        
        # 修复换行符在字符串中的问题
        json_str = re.sub(r'(?<!\\)\n(?![}\]])', '\\n', json_str)
        
        return json_str
    
    def _progressive_quote_fix(self, json_str: str) -> str:
        """渐进式引号修复 - 增强版"""
        import re
        
        # 修复未转义的反斜杠
        json_str = re.sub(r'(?<!\\)\\(?=")', r"\\\\", json_str)
        
        # 修复字符串内容中的特殊字符
        def fix_string_content(match):
            content = match.group(1)
            # 转义常见的特殊字符
            content = content.replace('\\', '\\\\')
            content = content.replace('\n', '\\n')
            content = content.replace('\r', '\\r')
            content = content.replace('\t', '\\t')
            content = content.replace('"', '\\"')
            return f'"{content}"'
        
        # 应用字符串内容修复
        json_str = re.sub(r'"([^"]*(?:\\.[^"]*)*)"', fix_string_content, json_str)
        
        # 修复LaTeX公式中的反斜杠
        json_str = re.sub(r'\\([a-zA-Z]+)', r'\\\\\\1', json_str)
        
        return json_str
    
    def _extract_fields_with_regex(self, response: str) -> dict:
        """使用正则表达式提取字段作为最后手段 - 保证不崩溃"""
        import re
        
        print("Warning: Using regex fallback for JSON parsing")
        
        try:
            # 提取 detailed_description 或 description
            desc_patterns = [
                r'"detailed_description":\s*"([^"]*(?:\\.[^"]*)*)"',
                r'"description":\s*"([^"]*(?:\\.[^"]*)*)"',
                r'"summary":\s*"([^"]*(?:\\.[^"]*)*)"'
            ]
            
            description = ""
            for pattern in desc_patterns:
                desc_match = re.search(pattern, response, re.DOTALL)
                if desc_match:
                    description = desc_match.group(1)
                    break
            
            # 如果没有找到描述，使用响应的前200个字符
            if not description:
                description = response[:200].replace('"', '\\"')
            
            # 提取 entity_name
            name_patterns = [
                r'"entity_name":\s*"([^"]*(?:\\.[^"]*)*)"',
                r'"name":\s*"([^"]*(?:\\.[^"]*)*)"'
            ]
            
            entity_name = "unknown_entity"
            for pattern in name_patterns:
                name_match = re.search(pattern, response)
                if name_match:
                    entity_name = name_match.group(1)
                    break
            
            # 提取 entity_type
            type_patterns = [
                r'"entity_type":\s*"([^"]*(?:\\.[^"]*)*)"',
                r'"type":\s*"([^"]*(?:\\.[^"]*)*)"'
            ]
            
            entity_type = "unknown"
            for pattern in type_patterns:
                type_match = re.search(pattern, response)
                if type_match:
                    entity_type = type_match.group(1)
                    break
            
            # 提取 summary
            summary_patterns = [
                r'"summary":\s*"([^"]*(?:\\.[^"]*)*)"',
                r'"brief":\s*"([^"]*(?:\\.[^"]*)*)"'
            ]
            
            summary = description[:100] + "..." if len(description) > 100 else description
            for pattern in summary_patterns:
                summary_match = re.search(pattern, response, re.DOTALL)
                if summary_match:
                    summary = summary_match.group(1)
                    break
            
            # 构建最终结果
            result = {
                "detailed_description": description,
                "entity_info": {
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "summary": summary,
                },
            }
            
            return result
            
        except Exception as e:
            print(f"Error in regex fallback: {e}")
            return self._get_fallback_result()
    
    def _get_fallback_result(self) -> dict:
        """获取最终回退结果 - 保证永远不会崩溃"""
        return {
            "detailed_description": "Failed to parse response",
            "entity_info": {
                "entity_name": "unknown_entity",
                "entity_type": "unknown",
                "summary": "Failed to parse response",
            },
        }


class ImageModalProcessor(BaseModalProcessor):
    """图像多模态处理器 - 参考 RAGAnything 的 ImageModalProcessor"""
    
    def __init__(self, config: ModalProcessorConfig):
        super().__init__(config)
        
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """处理图像项目"""
        try:
            # 生成描述和实体信息
            enhanced_description, entity_info = await self.generate_description_only(
                item.content, item.content_type, item.item_info
            )
            
            # 构建完整的图像内容
            if isinstance(item.content, str):
                try:
                    content_data = json.loads(item.content)
                except json.JSONDecodeError:
                    content_data = {"description": item.content}
            else:
                content_data = item.content
            
            image_path = content_data.get("img_path", "")
            captions = content_data.get("image_caption", content_data.get("img_caption", []))
            footnotes = content_data.get("image_footnote", content_data.get("img_footnote", []))
            
            # 构建块内容
            chunk_content = f"""
Image: {image_path}
Captions: {', '.join(captions) if captions else 'None'}
Footnotes: {', '.join(footnotes) if footnotes else 'None'}
Enhanced Description: {enhanced_description}
"""
            
            return ProcessedModalItem(
                enhanced_description=enhanced_description,
                entity_info=entity_info,
                chunk_content=chunk_content,
                original_item=item
            )
            
        except Exception as e:
            print(f"Error processing image content: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": f"image_{hash(str(item.content))}",
                "entity_type": "image",
                "summary": f"Image content: {str(item.content)[:100]}",
            }
            return ProcessedModalItem(
                enhanced_description=str(item.content),
                entity_info=fallback_entity,
                chunk_content=str(item.content),
                original_item=item
            )
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """仅生成图像描述，不进行实体关系提取"""
        try:
            # 解析图像内容
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"description": modal_content}
            else:
                content_data = modal_content
            
            image_path = content_data.get("img_path")
            captions = content_data.get("image_caption", content_data.get("img_caption", []))
            footnotes = content_data.get("image_footnote", content_data.get("img_footnote", []))
            
            # 验证图像路径
            if not image_path:
                raise ValueError(f"No image path provided in modal_content: {modal_content}")
            
            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")
            
            # 构建视觉分析提示
            vision_prompt = f"""
Analyze this image and provide a detailed description.

Image Path: {image_path}
Captions: {captions if captions else 'None'}
Footnotes: {footnotes if footnotes else 'None'}
Entity Name: {entity_name if entity_name else 'unique descriptive name for this image'}

Please provide a JSON response with:
{{
    "detailed_description": "detailed visual analysis of the image",
    "entity_info": {{
        "entity_name": "descriptive name for this image",
        "entity_type": "image",
        "summary": "brief summary of the image content"
    }}
}}
"""
            
            # 编码图像为 base64
            image_base64 = self._encode_image_to_base64(image_path)
            if not image_base64:
                raise RuntimeError(f"Failed to encode image to base64: {image_path}")
            
            # 调用视觉模型（这里需要实际的模型调用）
            # 暂时使用模拟响应
            response = await self._call_vision_model(vision_prompt, image_base64)
            
            # 解析响应
            enhanced_description, entity_info = self._parse_response(response, entity_name)
            
            return enhanced_description, entity_info
            
        except Exception as e:
            print(f"Error generating image description: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"image_{hash(str(modal_content))}",
                "entity_type": "image",
                "summary": f"Image content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity
    
    async def generate_description_with_context(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        context_text: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """使用上下文生成图像描述"""
        try:
            # 解析图像内容
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"description": modal_content}
            else:
                content_data = modal_content

            image_path = content_data.get("img_path")
            captions = content_data.get("image_caption", content_data.get("img_caption", []))
            footnotes = content_data.get("image_footnote", content_data.get("img_footnote", []))

            # 验证图像路径
            if not image_path:
                raise ValueError(f"No image path provided in modal_content: {modal_content}")

            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")

            # 构建上下文感知的视觉分析提示
            vision_prompt = self._build_context_aware_prompt(
                image_path, captions, footnotes, entity_name, context_text
            )

            # 编码图像为 base64
            image_base64 = self._encode_image_to_base64(image_path)
            if not image_base64:
                raise RuntimeError(f"Failed to encode image to base64: {image_path}")

            # 调用视觉模型
            response = await self._call_vision_model_with_context(vision_prompt, image_base64, context_text)

            # 解析响应
            enhanced_description, entity_info = self._parse_response(response, entity_name)

            return enhanced_description, entity_info

        except Exception as e:
            print(f"Error generating image description with context: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"image_{hash(str(modal_content))}",
                "entity_type": "image",
                "summary": f"Image content with context error: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    def _build_context_aware_prompt(
        self,
        image_path: str,
        captions: List[str],
        footnotes: List[str],
        entity_name: Optional[str],
        context_text: Optional[str]
    ) -> str:
        """构建上下文感知的图像分析提示 - 参考 RAGAnything 的做法"""
        # 在 prompt 级别融入上下文，而不是简单附加
        context_section = f"""
Context from surrounding content: {context_text}

""" if context_text else ""

        prompt = f"""
{context_section}Image details:
- Image Path: {image_path}
- Captions: {captions if captions else 'None'}
- Footnotes: {footnotes if footnotes else 'None'}
- Entity Name: {entity_name if entity_name else 'unique descriptive name for this image'}

Please analyze how the image relates to the surrounding text and provide a detailed description.

Please provide a JSON response with:
{{
    "detailed_description": "detailed visual analysis considering the context",
    "entity_info": {{
        "entity_name": "descriptive name for this image",
        "entity_type": "image",
        "summary": "brief summary of the image content considering context"
    }}
}}
"""
        return prompt

    async def _call_vision_model_with_context(self, prompt: str, image_base64: str, context_text: Optional[str]) -> str:
        """调用视觉模型（上下文感知版本）"""
        # 这里需要实际的视觉模型调用
        # 暂时返回模拟响应，但可以包含上下文信息
        if context_text:
            return f"""
{{
    "detailed_description": "This image analysis considers the following context: {context_text[:200]}... The image appears to be related to the surrounding content.",
    "entity_info": {{
        "entity_name": "Context-Aware Image",
        "entity_type": "image",
        "summary": "Image analyzed with context consideration"
    }}
}}
"""
        else:
            # 回退到普通视觉模型调用
            return await self._call_vision_model(prompt, image_base64)

    def _encode_image_to_base64(self, image_path: str) -> str:
        """编码图像为 base64"""
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return encoded_string
        except Exception as e:
            print(f"Failed to encode image {image_path}: {e}")
            return ""
    
    async def _call_vision_model(self, prompt: str, image_base64: str) -> str:
        """调用视觉模型 - 需要实际实现"""
        # 这里需要实际的视觉模型调用
        # 暂时返回模拟响应
        return """
{
    "detailed_description": "This is a detailed analysis of the image content.",
    "entity_info": {
        "entity_name": "Sample Image",
        "entity_type": "image",
        "summary": "A sample image for testing purposes"
    }
}
"""
    
    def _parse_response(self, response: str, entity_name: Optional[str] = None) -> tuple[str, Dict[str, Any]]:
        """解析模型响应"""
        try:
            response_data = self._robust_json_parse(response)
            
            description = response_data.get("detailed_description", "")
            entity_data = response_data.get("entity_info", {})
            
            if not description or not entity_data:
                raise ValueError("Missing required fields in response")
            
            if not all(key in entity_data for key in ["entity_name", "entity_type", "summary"]):
                raise ValueError("Missing required fields in entity_info")
            
            if entity_name:
                entity_data["entity_name"] = entity_name
            
            return description, entity_data
            
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            print(f"Error parsing image analysis response: {e}")
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"image_{hash(response)}",
                "entity_type": "image",
                "summary": response[:100] + "..." if len(response) > 100 else response,
            }
            return response, fallback_entity


class TableModalProcessor(BaseModalProcessor):
    """表格多模态处理器"""
    
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """处理表格项目"""
        try:
            # 生成描述和实体信息
            enhanced_description, entity_info = await self.generate_description_only(
                item.content, item.content_type, item.item_info
            )
            
            # 解析表格内容
            if isinstance(item.content, str):
                try:
                    content_data = json.loads(item.content)
                except json.JSONDecodeError:
                    content_data = {"table_body": item.content}
            else:
                content_data = item.content
            
            table_img_path = content_data.get("img_path")
            table_caption = content_data.get("table_caption", [])
            table_body = content_data.get("table_body", "")
            table_footnote = content_data.get("table_footnote", [])
            
            # 构建完整表格内容
            chunk_content = f"""
Table Image: {table_img_path}
Caption: {', '.join(table_caption) if table_caption else 'None'}
Body: {table_body}
Footnote: {', '.join(table_footnote) if table_footnote else 'None'}
Enhanced Description: {enhanced_description}
"""
            
            return ProcessedModalItem(
                enhanced_description=enhanced_description,
                entity_info=entity_info,
                chunk_content=chunk_content,
                original_item=item
            )
            
        except Exception as e:
            print(f"Error processing table content: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": f"table_{hash(str(item.content))}",
                "entity_type": "table",
                "summary": f"Table content: {str(item.content)[:100]}",
            }
            return ProcessedModalItem(
                enhanced_description=str(item.content),
                entity_info=fallback_entity,
                chunk_content=str(item.content),
                original_item=item
            )
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """仅生成表格描述"""
        # 简化实现，实际中需要调用 LLM
        fallback_entity = {
            "entity_name": entity_name if entity_name else f"table_{hash(str(modal_content))}",
            "entity_type": "table",
            "summary": f"Table content: {str(modal_content)[:100]}",
        }
        return str(modal_content), fallback_entity

    async def generate_description_with_context(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        context_text: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """使用上下文生成表格描述"""
        # 如果有上下文信息，将其包含在描述中
        if context_text:
            enhanced_content = f"""Table Analysis with Context:

Context Information:
{context_text}

Table Content:
{modal_content}

Please analyze this table considering the surrounding context."""

            # 在实际实现中，这里应该调用LLM来分析表格和上下文
            # 目前简化实现：返回包含上下文的描述
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"table_{hash(str(modal_content))}",
                "entity_type": "table",
                "summary": f"Table with context: {str(context_text)[:100]}...",
            }
            return enhanced_content, fallback_entity
        else:
            # 无上下文时回退到基础处理
            return await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )


class EquationModalProcessor(BaseModalProcessor):
    """公式多模态处理器"""
    
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """处理公式项目"""
        try:
            # 生成描述和实体信息
            enhanced_description, entity_info = await self.generate_description_only(
                item.content, item.content_type, item.item_info
            )
            
            # 解析公式内容
            if isinstance(item.content, str):
                try:
                    content_data = json.loads(item.content)
                except json.JSONDecodeError:
                    content_data = {"equation": item.content}
            else:
                content_data = item.content
            
            equation_text = content_data.get("text")
            equation_format = content_data.get("text_format", "")
            
            # 构建完整公式内容
            chunk_content = f"""
Equation: {equation_text}
Format: {equation_format}
Enhanced Description: {enhanced_description}
"""
            
            return ProcessedModalItem(
                enhanced_description=enhanced_description,
                entity_info=entity_info,
                chunk_content=chunk_content,
                original_item=item
            )
            
        except Exception as e:
            print(f"Error processing equation content: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": f"equation_{hash(str(item.content))}",
                "entity_type": "equation",
                "summary": f"Equation content: {str(item.content)[:100]}",
            }
            return ProcessedModalItem(
                enhanced_description=str(item.content),
                entity_info=fallback_entity,
                chunk_content=str(item.content),
                original_item=item
            )
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """仅生成公式描述"""
        # 简化实现
        fallback_entity = {
            "entity_name": entity_name if entity_name else f"equation_{hash(str(modal_content))}",
            "entity_type": "equation",
            "summary": f"Equation content: {str(modal_content)[:100]}",
        }
        return str(modal_content), fallback_entity

    async def generate_description_with_context(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        context_text: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """使用上下文生成公式描述"""
        # 如果有上下文信息，将其包含在描述中
        if context_text:
            enhanced_content = f"""Equation Analysis with Context:

Context Information:
{context_text}

Equation Content:
{modal_content}

Please analyze this mathematical equation considering the surrounding context."""

            # 在实际实现中，这里应该调用LLM来分析公式和上下文
            # 目前简化实现：返回包含上下文的描述
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"equation_{hash(str(modal_content))}",
                "entity_type": "equation",
                "summary": f"Equation with context: {str(context_text)[:100]}...",
            }
            return enhanced_content, fallback_entity
        else:
            # 无上下文时回退到基础处理
            return await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )


class GenericModalProcessor(BaseModalProcessor):
    """通用多模态处理器"""
    
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """处理通用项目"""
        try:
            # 生成描述和实体信息
            enhanced_description, entity_info = await self.generate_description_only(
                item.content, item.content_type, item.item_info
            )
            
            # 构建完整内容
            chunk_content = f"""
Content Type: {item.content_type.title()}
Content: {str(item.content)}
Enhanced Description: {enhanced_description}
"""
            
            return ProcessedModalItem(
                enhanced_description=enhanced_description,
                entity_info=entity_info,
                chunk_content=chunk_content,
                original_item=item
            )
            
        except Exception as e:
            print(f"Error processing {item.content_type} content: {e}")
            # 回退处理
            fallback_entity = {
                "entity_name": f"{item.content_type}_{hash(str(item.content))}",
                "entity_type": item.content_type,
                "summary": f"{item.content_type} content: {str(item.content)[:100]}",
            }
            return ProcessedModalItem(
                enhanced_description=str(item.content),
                entity_info=fallback_entity,
                chunk_content=str(item.content),
                original_item=item
            )
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """仅生成通用描述"""
        # 简化实现
        fallback_entity = {
            "entity_name": entity_name if entity_name else f"{content_type}_{hash(str(modal_content))}",
            "entity_type": content_type,
            "summary": f"{content_type} content: {str(modal_content)[:100]}",
        }
        return str(modal_content), fallback_entity

    async def generate_description_with_context(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        context_text: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """使用上下文生成通用描述"""
        # 如果有上下文信息，将其包含在描述中
        if context_text:
            enhanced_content = f"""{content_type.title()} Analysis with Context:

Context Information:
{context_text}

{content_type.title()} Content:
{modal_content}

Please analyze this {content_type} content considering the surrounding context."""

            # 在实际实现中，这里应该调用LLM来分析内容和上下文
            # 目前简化实现：返回包含上下文的描述
            fallback_entity = {
                "entity_name": entity_name if entity_name else f"{content_type}_{hash(str(modal_content))}",
                "entity_type": content_type,
                "summary": f"{content_type} with context: {str(context_text)[:100]}...",
            }
            return enhanced_content, fallback_entity
        else:
            # 无上下文时回退到基础处理
            return await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )