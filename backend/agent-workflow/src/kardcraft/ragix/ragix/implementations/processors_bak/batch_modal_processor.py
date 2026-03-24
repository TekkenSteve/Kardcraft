# implementations/processors/batch_modal_processor.py - 批量多模态处理器
"""
批量多模态处理器 - 参考 RAGAnything 的两阶段处理设计

Stage 1: 并发生成所有描述
Stage 2: 批量创建实体和关系
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from ...protocols.processors_bak import ModalItem, ProcessedModalItem, ModalProcessorConfig
from .modal import BaseModalProcessor


@dataclass
class BatchProcessingResult:
    """批处理结果"""
    processed_items: List[ProcessedModalItem]
    processing_stats: Dict[str, Any]
    errors: List[Dict[str, Any]]


class BatchModalProcessor(BaseModalProcessor):
    """批量多模态处理器 - 实现两阶段处理"""
    
    def __init__(self, config: ModalProcessorConfig):
        super().__init__(config)
        self.batch_size = getattr(config, 'batch_size', 10)
        self.max_concurrent = getattr(config, 'max_concurrent', 5)
        
    async def process_batch_with_stats(self, items: List[ModalItem]) -> BatchProcessingResult:
        """带统计信息的批处理"""
        import time
        start_time = time.time()
        
        errors = []
        processed_items = []
        
        try:
            # 分批处理
            for i in range(0, len(items), self.batch_size):
                batch = items[i:i + self.batch_size]
                batch_results = await self.process_batch(batch)
                processed_items.extend(batch_results)
                
        except Exception as e:
            errors.append({
                "error": str(e),
                "batch_index": i // self.batch_size,
                "timestamp": time.time()
            })
        
        processing_time = time.time() - start_time
        
        stats = {
            "total_items": len(items),
            "processed_items": len(processed_items),
            "failed_items": len(errors),
            "processing_time": processing_time,
            "items_per_second": len(processed_items) / processing_time if processing_time > 0 else 0,
            "batch_size": self.batch_size,
            "max_concurrent": self.max_concurrent
        }
        
        return BatchProcessingResult(
            processed_items=processed_items,
            processing_stats=stats,
            errors=errors
        )
    
    async def process_batch_two_stage(self, items: List[ModalItem]) -> List[ProcessedModalItem]:
        """两阶段批处理 - 参考 RAGAnything 的设计
        
        Stage 1: generate_description_only() - 并发生成所有描述
        Stage 2: _create_entity_and_chunk() - 批量创建实体和 chunk
        """
        # Stage 1: 并发生成描述
        descriptions_and_entities = await self._stage1_generate_descriptions(items)
        
        # Stage 2: 批量创建实体和块
        processed_items = await self._stage2_create_entities_and_chunks(items, descriptions_and_entities)
        
        return processed_items
    
    async def _stage1_generate_descriptions(self, items: List[ModalItem]) -> List[Tuple[str, Dict[str, Any]]]:
        """Stage 1: 并发生成所有描述 - 分离 I/O 密集型操作"""
        # 创建信号量来限制 I/O 并发数（可以设置较高）
        io_semaphore = asyncio.Semaphore(self.max_concurrent * 2)  # I/O 密集型，可以更高并发
        
        async def generate_with_io_semaphore(item: ModalItem) -> Tuple[str, Dict[str, Any]]:
            async with io_semaphore:
                if self.has_context_support():
                    return await self.generate_description_with_context(
                        item.content, item.content_type, item.item_info
                    )
                else:
                    return await self.generate_description_only(
                        item.content, item.content_type, item.item_info
                    )
        
        # 并发执行所有描述生成任务
        tasks = [generate_with_io_semaphore(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error generating description for item {i}: {result}")
                # 创建回退结果
                fallback_entity = {
                    "entity_name": f"{items[i].content_type}_{hash(str(items[i].content))}",
                    "entity_type": items[i].content_type,
                    "summary": f"Error processing {items[i].content_type}: {str(result)[:100]}",
                }
                processed_results.append((str(items[i].content), fallback_entity))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _stage2_create_entities_and_chunks(
        self, 
        items: List[ModalItem], 
        descriptions_and_entities: List[Tuple[str, Dict[str, Any]]]
    ) -> List[ProcessedModalItem]:
        """Stage 2: 批量创建实体和块 - 控制存储操作并发"""
        # 创建信号量来限制存储操作并发数（较低，避免数据库压力）
        storage_semaphore = asyncio.Semaphore(max(1, self.max_concurrent // 2))  # 存储密集型，较低并发
        
        async def create_with_storage_semaphore(
            item: ModalItem, 
            description_and_entity: Tuple[str, Dict[str, Any]]
        ) -> ProcessedModalItem:
            async with storage_semaphore:
                description, entity_info = description_and_entity
                
                try:
                    # 构建块内容
                    chunk_content = self._build_chunk_content_for_item(item, description)
                    
                    # 创建 belongs_to 关系
                    belongs_to_relations = await self._create_belongs_to_relations(item, entity_info)
                    
                    # 创建处理后的项目
                    processed_item = ProcessedModalItem(
                        enhanced_description=description,
                        entity_info=entity_info,
                        chunk_content=chunk_content,
                        original_item=item
                    )
                    
                    # 将关系信息添加到处理后的项目中
                    if belongs_to_relations:
                        processed_item.belongs_to_relations = belongs_to_relations
                    
                    return processed_item
                    
                except Exception as e:
                    print(f"Error creating entity and chunk for item: {e}")
                    # 创建回退项目
                    fallback_entity = {
                        "entity_name": f"{item.content_type}_{hash(str(item.content))}",
                        "entity_type": item.content_type,
                        "summary": f"Fallback {item.content_type}: {str(item.content)[:100]}",
                    }
                    return ProcessedModalItem(
                        enhanced_description=str(item.content),
                        entity_info=fallback_entity,
                        chunk_content=str(item.content),
                        original_item=item
                    )
        
        # 并发执行存储操作（受限并发）
        tasks = [
            create_with_storage_semaphore(item, desc_entity) 
            for item, desc_entity in zip(items, descriptions_and_entities)
        ]
        
        processed_items = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        final_results = []
        for i, result in enumerate(processed_items):
            if isinstance(result, Exception):
                print(f"Error in storage stage for item {i}: {result}")
                # 创建最终回退项目
                fallback_entity = {
                    "entity_name": f"{items[i].content_type}_{hash(str(items[i].content))}",
                    "entity_type": items[i].content_type,
                    "summary": f"Final fallback {items[i].content_type}",
                }
                final_results.append(ProcessedModalItem(
                    enhanced_description=str(items[i].content),
                    entity_info=fallback_entity,
                    chunk_content=str(items[i].content),
                    original_item=items[i]
                ))
            else:
                final_results.append(result)
        
        return final_results
    
    async def _create_belongs_to_relations(
        self, 
        item: ModalItem, 
        entity_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """创建 belongs_to 关系 - 参考 RAGAnything 的关系构建"""
        relations = []
        
        try:
            modal_entity_name = entity_info.get("entity_name", "unknown")
            
            # 1. 与文档的关系
            if item.item_info and item.item_info.get("document_id"):
                document_relation = {
                    "source": modal_entity_name,
                    "target": item.item_info.get("document_id"),
                    "relation": "belongs_to",
                    "description": f"Entity {modal_entity_name} belongs to document",
                    "keywords": "belongs_to,part_of,contained_in",
                    "weight": 10.0,  # 高权重
                    "properties": {
                        "position": item.item_info.get("position", {}),
                        "element_id": item.item_info.get("element_id", ""),
                        "content_type": item.content_type
                    }
                }
                relations.append(document_relation)
            
            # 2. 与周围文本实体的关系
            if item.item_info and item.item_info.get("context_entities"):
                context_entities = item.item_info.get("context_entities", [])
                for context_entity in context_entities:
                    if context_entity != modal_entity_name:
                        context_relation = {
                            "source": modal_entity_name,
                            "target": context_entity,
                            "relation": "related_to",
                            "description": f"Entity {modal_entity_name} is related to {context_entity}",
                            "keywords": "related_to,contextual,nearby",
                            "weight": 5.0,  # 中等权重
                            "properties": {
                                "relation_type": "contextual",
                                "content_type": item.content_type
                            }
                        }
                        relations.append(context_relation)
            
            # 3. 特定内容类型的关系
            if item.content_type == "image":
                # 图片与其标题/说明的关系
                relations.extend(await self._create_image_relations(item, entity_info))
            elif item.content_type == "table":
                # 表格与其数据的关系
                relations.extend(await self._create_table_relations(item, entity_info))
            elif item.content_type == "equation":
                # 公式与其变量的关系
                relations.extend(await self._create_equation_relations(item, entity_info))
            
        except Exception as e:
            print(f"Error creating belongs_to relations: {e}")
        
        return relations
    
    async def _create_image_relations(self, item: ModalItem, entity_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建图片特定的关系"""
        relations = []
        
        try:
            import json
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            entity_name = entity_info.get("entity_name", "unknown")
            
            # 与图片说明的关系
            captions = content_data.get("image_caption", content_data.get("img_caption", []))
            if captions:
                for i, caption in enumerate(captions):
                    if caption.strip():
                        caption_entity = f"caption_{hash(caption)}_{i}"
                        relation = {
                            "source": entity_name,
                            "target": caption_entity,
                            "relation": "has_caption",
                            "description": f"Image {entity_name} has caption: {caption[:50]}...",
                            "keywords": "has_caption,describes,explains",
                            "weight": 8.0,
                            "properties": {
                                "caption_text": caption,
                                "caption_index": i
                            }
                        }
                        relations.append(relation)
            
            # 与图片注释的关系
            footnotes = content_data.get("image_footnote", content_data.get("img_footnote", []))
            if footnotes:
                for i, footnote in enumerate(footnotes):
                    if footnote.strip():
                        footnote_entity = f"footnote_{hash(footnote)}_{i}"
                        relation = {
                            "source": entity_name,
                            "target": footnote_entity,
                            "relation": "has_footnote",
                            "description": f"Image {entity_name} has footnote: {footnote[:50]}...",
                            "keywords": "has_footnote,annotates,references",
                            "weight": 6.0,
                            "properties": {
                                "footnote_text": footnote,
                                "footnote_index": i
                            }
                        }
                        relations.append(relation)
                        
        except Exception as e:
            print(f"Error creating image relations: {e}")
        
        return relations
    
    async def _create_table_relations(self, item: ModalItem, entity_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建表格特定的关系"""
        relations = []
        
        try:
            import json
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            entity_name = entity_info.get("entity_name", "unknown")
            
            # 与表格标题的关系
            captions = content_data.get("table_caption", [])
            if captions:
                for i, caption in enumerate(captions):
                    if caption.strip():
                        caption_entity = f"table_caption_{hash(caption)}_{i}"
                        relation = {
                            "source": entity_name,
                            "target": caption_entity,
                            "relation": "has_title",
                            "description": f"Table {entity_name} has title: {caption[:50]}...",
                            "keywords": "has_title,titled,named",
                            "weight": 8.0,
                            "properties": {
                                "title_text": caption,
                                "title_index": i
                            }
                        }
                        relations.append(relation)
            
            # 与表格数据的关系（如果有结构化数据）
            table_body = content_data.get("table_body", "")
            if table_body:
                # 简单解析表格数据，创建数据实体关系
                data_entity = f"table_data_{hash(table_body)}"
                relation = {
                    "source": entity_name,
                    "target": data_entity,
                    "relation": "contains_data",
                    "description": f"Table {entity_name} contains structured data",
                    "keywords": "contains_data,includes,holds",
                    "weight": 9.0,
                    "properties": {
                        "data_preview": table_body[:200],
                        "data_type": "tabular"
                    }
                }
                relations.append(relation)
                        
        except Exception as e:
            print(f"Error creating table relations: {e}")
        
        return relations
    
    async def _create_equation_relations(self, item: ModalItem, entity_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建公式特定的关系"""
        relations = []
        
        try:
            import json, re
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            entity_name = entity_info.get("entity_name", "unknown")
            equation_text = content_data.get("text", "")
            
            if equation_text:
                # 简单的变量提取（匹配单个字母变量）
                variables = re.findall(r'\b[a-zA-Z]\b', equation_text)
                unique_variables = list(set(variables))
                
                for variable in unique_variables:
                    variable_entity = f"variable_{variable}_{hash(equation_text)}"
                    relation = {
                        "source": entity_name,
                        "target": variable_entity,
                        "relation": "contains_variable",
                        "description": f"Equation {entity_name} contains variable {variable}",
                        "keywords": "contains_variable,uses,includes",
                        "weight": 7.0,
                        "properties": {
                            "variable_name": variable,
                            "equation_context": equation_text
                        }
                    }
                    relations.append(relation)
                        
        except Exception as e:
            print(f"Error creating equation relations: {e}")
        
        return relations
    
    def _build_chunk_content_for_item(self, item: ModalItem, description: str) -> str:
        """为特定项目构建块内容"""
        base_content = f"""
Content Type: {item.content_type.title()}
Content: {str(item.content)[:500]}
Enhanced Description: {description}
"""
        
        # 根据内容类型添加特定信息
        if item.content_type == "image":
            return self._build_image_chunk_content(item, description)
        elif item.content_type == "table":
            return self._build_table_chunk_content(item, description)
        elif item.content_type == "equation":
            return self._build_equation_chunk_content(item, description)
        else:
            return base_content
    
    def _build_image_chunk_content(self, item: ModalItem, description: str) -> str:
        """构建图像块内容"""
        try:
            import json
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            image_path = content_data.get("img_path", "")
            captions = content_data.get("image_caption", content_data.get("img_caption", []))
            footnotes = content_data.get("image_footnote", content_data.get("img_footnote", []))
            
            return f"""
Image: {image_path}
Captions: {', '.join(captions) if captions else 'None'}
Footnotes: {', '.join(footnotes) if footnotes else 'None'}
Enhanced Description: {description}
"""
        except Exception:
            return f"""
Content Type: Image
Content: {str(item.content)[:500]}
Enhanced Description: {description}
"""
    
    def _build_table_chunk_content(self, item: ModalItem, description: str) -> str:
        """构建表格块内容"""
        try:
            import json
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            table_img_path = content_data.get("img_path")
            table_caption = content_data.get("table_caption", [])
            table_body = content_data.get("table_body", "")
            table_footnote = content_data.get("table_footnote", [])
            
            return f"""
Table Image: {table_img_path}
Caption: {', '.join(table_caption) if table_caption else 'None'}
Body: {table_body}
Footnote: {', '.join(table_footnote) if table_footnote else 'None'}
Enhanced Description: {description}
"""
        except Exception:
            return f"""
Content Type: Table
Content: {str(item.content)[:500]}
Enhanced Description: {description}
"""
    
    def _build_equation_chunk_content(self, item: ModalItem, description: str) -> str:
        """构建公式块内容"""
        try:
            import json
            if isinstance(item.content, str):
                content_data = json.loads(item.content)
            else:
                content_data = item.content
            
            equation_text = content_data.get("text")
            equation_format = content_data.get("text_format", "")
            
            return f"""
Equation: {equation_text}
Format: {equation_format}
Enhanced Description: {description}
"""
        except Exception:
            return f"""
Content Type: Equation
Content: {str(item.content)[:500]}
Enhanced Description: {description}
"""
    
    async def merge_nodes_and_edges(self, processed_items: List[ProcessedModalItem]) -> Dict[str, Any]:
        """合并节点和边 - 用于知识图谱集成"""
        nodes = []
        edges = []
        relationships = []
        
        for item in processed_items:
            try:
                entity_info = item.entity_info
                
                # 创建实体节点
                node = {
                    "id": entity_info.get("entity_name", "unknown"),
                    "type": entity_info.get("entity_type", "unknown"),
                    "properties": {
                        "summary": entity_info.get("summary", ""),
                        "description": item.enhanced_description,
                        "content_type": item.original_item.content_type,
                        "original_content": str(item.original_item.content)[:200]
                    }
                }
                nodes.append(node)
                
                # 创建与原文的关系（belongs_to）
                if item.original_item.item_info and item.original_item.item_info.get("document_id"):
                    edge = {
                        "source": entity_info.get("entity_name", "unknown"),
                        "target": item.original_item.item_info.get("document_id"),
                        "relation": "belongs_to",
                        "properties": {
                            "position": item.original_item.item_info.get("position", {}),
                            "element_id": item.original_item.item_info.get("element_id", "")
                        }
                    }
                    edges.append(edge)
                
                # 创建关系向量数据库条目
                relationship = {
                    "entity_name": entity_info.get("entity_name", "unknown"),
                    "entity_type": entity_info.get("entity_type", "unknown"),
                    "chunk_content": item.chunk_content,
                    "enhanced_description": item.enhanced_description
                }
                relationships.append(relationship)
                
            except Exception as e:
                print(f"Error creating node/edge for item: {e}")
                continue
        
        return {
            "nodes": nodes,
            "edges": edges,
            "relationships": relationships,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "total_relationships": len(relationships)
            }
        }
    
    # 实现基类的抽象方法
    async def process(self, item: ModalItem) -> ProcessedModalItem:
        """单个项目处理 - 委托给批处理"""
        results = await self.process_batch([item])
        return results[0] if results else ProcessedModalItem(
            enhanced_description=str(item.content),
            entity_info={"entity_name": "unknown", "entity_type": item.content_type, "summary": ""},
            chunk_content=str(item.content),
            original_item=item
        )
    
    async def generate_description_only(
        self,
        modal_content: Any,
        content_type: str,
        item_info: Optional[Dict[str, Any]] = None,
        entity_name: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """生成描述 - 简化实现"""
        fallback_entity = {
            "entity_name": entity_name if entity_name else f"{content_type}_{hash(str(modal_content))}",
            "entity_type": content_type,
            "summary": f"{content_type} content: {str(modal_content)[:100]}",
        }
        return str(modal_content), fallback_entity