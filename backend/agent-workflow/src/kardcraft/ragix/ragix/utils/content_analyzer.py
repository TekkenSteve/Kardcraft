# utils/content_analyzer.py - 内容分析工具
"""
内容分析工具

提供文档内容分析、复杂度评估、统计信息生成等功能
参考 RAG-Anything 的内容分析逻辑
"""

import hashlib
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from .logger import logger


class DocumentComplexity(Enum):
    """文档复杂度枚举"""
    SIMPLE = "simple"           # 纯文本文档
    MODERATE = "moderate"       # 包含少量多模态内容
    COMPLEX = "complex"         # 大量多模态内容
    MULTIMODAL_HEAVY = "multimodal_heavy"  # 以多模态内容为主


@dataclass
class ContentStats:
    """内容统计信息"""
    text_length: int
    text_blocks: int
    multimodal_count: int
    multimodal_types: Dict[str, int]
    total_items: int
    multimodal_ratio: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "text_length": self.text_length,
            "text_blocks": self.text_blocks,
            "multimodal_count": self.multimodal_count,
            "multimodal_types": self.multimodal_types,
            "total_items": self.total_items,
            "multimodal_ratio": self.multimodal_ratio
        }


@dataclass
class ContentAnalysis:
    """内容分析结果"""
    text_content: str
    multimodal_items: List[Dict[str, Any]]
    complexity: DocumentComplexity
    content_stats: ContentStats
    doc_id: str
    
    @property
    def has_multimodal_content(self) -> bool:
        """是否包含多模态内容"""
        return len(self.multimodal_items) > 0
    
    @property
    def should_use_multimodal_processing(self) -> bool:
        """是否应该使用多模态处理"""
        return self.complexity in [DocumentComplexity.COMPLEX, DocumentComplexity.MULTIMODAL_HEAVY]


class ContentAnalyzer:
    """内容分析器 - 参考 RAG-Anything 的 separate_content 逻辑"""
    
    def __init__(self):
        # 复杂度评估阈值
        self.complexity_thresholds = {
            "moderate_ratio": 0.1,    # 多模态内容占比 > 10% 为 moderate
            "complex_ratio": 0.3,     # 多模态内容占比 > 30% 为 complex
            "heavy_ratio": 0.6,       # 多模态内容占比 > 60% 为 multimodal_heavy
            "moderate_count": 3,      # 多模态项目 > 3 个为 moderate
            "complex_count": 10,      # 多模态项目 > 10 个为 complex
        }
    
    def separate_content(self, content_list: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        分离文本内容和多模态内容
        
        Args:
            content_list: 从解析器获得的内容列表
            
        Returns:
            (text_content, multimodal_items): 纯文本内容和多模态项目列表
        """
        text_parts = []
        multimodal_items = []
        
        for item in content_list:
            content_type = item.get("type", "text")
            
            if content_type == "text":
                # 文本内容
                text = item.get("text", "")
                if text.strip():
                    text_parts.append(text)
            else:
                # 多模态内容 (image, table, equation, etc.)
                multimodal_items.append(item)
        
        # 合并所有文本内容
        text_content = "\n\n".join(text_parts)
        
        logger.info("Content separation complete:")
        logger.info(f"  - Text content length: {len(text_content)} characters")
        logger.info(f"  - Multimodal items count: {len(multimodal_items)}")
        
        # 统计多模态类型
        modal_types = {}
        for item in multimodal_items:
            modal_type = item.get("type", "unknown")
            modal_types[modal_type] = modal_types.get(modal_type, 0) + 1
        
        if modal_types:
            logger.info(f"  - Multimodal type distribution: {modal_types}")
        
        return text_content, multimodal_items
    
    def analyze_content(self, content_list: List[Dict[str, Any]], file_path: str = None) -> ContentAnalysis:
        """
        完整的内容分析
        
        Args:
            content_list: 内容列表
            file_path: 文件路径（用于生成doc_id）
            
        Returns:
            ContentAnalysis: 完整的内容分析结果
        """
        # 1. 分离内容
        text_content, multimodal_items = self.separate_content(content_list)
        
        # 2. 生成统计信息
        content_stats = self._generate_content_stats(text_content, multimodal_items)
        
        # 3. 评估复杂度
        complexity = self._assess_complexity(content_stats)
        
        # 4. 生成文档ID
        doc_id = self._generate_content_based_doc_id(content_list, file_path)
        
        return ContentAnalysis(
            text_content=text_content,
            multimodal_items=multimodal_items,
            complexity=complexity,
            content_stats=content_stats,
            doc_id=doc_id
        )
    
    def _generate_content_stats(self, text_content: str, multimodal_items: List[Dict[str, Any]]) -> ContentStats:
        """生成内容统计信息"""
        # 文本统计
        text_length = len(text_content)
        text_blocks = len([block for block in text_content.split('\n\n') if block.strip()])
        
        # 多模态统计
        multimodal_count = len(multimodal_items)
        multimodal_types = {}
        for item in multimodal_items:
            modal_type = item.get("type", "unknown")
            multimodal_types[modal_type] = multimodal_types.get(modal_type, 0) + 1
        
        # 总体统计
        total_items = text_blocks + multimodal_count
        multimodal_ratio = multimodal_count / total_items if total_items > 0 else 0.0
        
        return ContentStats(
            text_length=text_length,
            text_blocks=text_blocks,
            multimodal_count=multimodal_count,
            multimodal_types=multimodal_types,
            total_items=total_items,
            multimodal_ratio=multimodal_ratio
        )
    
    def _assess_complexity(self, stats: ContentStats) -> DocumentComplexity:
        """评估文档复杂度"""
        multimodal_ratio = stats.multimodal_ratio
        multimodal_count = stats.multimodal_count
        
        # 如果没有多模态内容，直接返回简单
        if multimodal_count == 0:
            return DocumentComplexity.SIMPLE
        
        # 基于比例和数量的复杂度评估
        if multimodal_ratio >= self.complexity_thresholds["heavy_ratio"]:
            return DocumentComplexity.MULTIMODAL_HEAVY
        elif (multimodal_ratio >= self.complexity_thresholds["complex_ratio"] or 
              multimodal_count >= self.complexity_thresholds["complex_count"]):
            return DocumentComplexity.COMPLEX
        elif (multimodal_ratio >= self.complexity_thresholds["moderate_ratio"] or 
              multimodal_count >= self.complexity_thresholds["moderate_count"]):
            return DocumentComplexity.MODERATE
        else:
            return DocumentComplexity.SIMPLE
    
    def _generate_content_based_doc_id(self, content_list: List[Dict[str, Any]], file_path: str = None) -> str:
        """
        基于内容生成文档ID - 参考 RAGAnything 的内容哈希策略
        
        Args:
            content_list: 内容列表
            file_path: 文件路径
            
        Returns:
            str: 文档ID
        """
        # 提取关键内容特征（文本+多模态标识）
        content_hash_data = []
        
        for item in content_list:
            content_type = item.get("type", "text")
            
            if content_type == "text":
                # 文本内容：使用去除空白后的内容
                text = item.get("text", "").strip()
                if text:
                    content_hash_data.append(text)
            elif content_type == "image":
                # 图片：使用路径和关键信息
                img_path = item.get("img_path", item.get("path", ""))
                caption = item.get("image_caption", item.get("img_caption", []))
                if isinstance(caption, list):
                    caption = " ".join(caption)
                content_hash_data.append(f"image:{img_path}:{caption}")
            elif content_type == "table":
                # 表格：使用表格内容和标题
                table_body = item.get("table_body", "")
                table_caption = item.get("table_caption", [])
                if isinstance(table_caption, list):
                    table_caption = " ".join(table_caption)
                content_hash_data.append(f"table:{table_body[:200]}:{table_caption}")
            elif content_type == "equation":
                # 公式：使用公式文本
                equation_text = item.get("text", "")
                content_hash_data.append(f"equation:{equation_text}")
            else:
                # 其他类型：使用类型和内容摘要
                content_str = str(item.get("content", item))[:100]
                content_hash_data.append(f"{content_type}:{content_str}")
        
        # 使用 MD5 哈希生成稳定 ID
        signature = "\n".join(content_hash_data)
        content_hash = hashlib.md5(signature.encode('utf-8')).hexdigest()
        
        return f"doc-{content_hash[:16]}"
    
    def display_content_stats(self, analysis: ContentAnalysis, file_path: str = None) -> None:
        """显示内容统计信息"""
        stats = analysis.content_stats
        
        logger.info("\n" + "="*50)
        logger.info("📊 DOCUMENT ANALYSIS REPORT")
        logger.info("="*50)
        
        if file_path:
            logger.info(f"📄 File: {file_path}")
        
        logger.info(f"🆔 Document ID: {analysis.doc_id}")
        logger.info(f"🔍 Complexity: {analysis.complexity.value.upper()}")
        
        logger.info("\n📝 TEXT CONTENT:")
        logger.info(f"  • Length: {stats.text_length:,} characters")
        logger.info(f"  • Blocks: {stats.text_blocks}")
        
        logger.info("\n🎨 MULTIMODAL CONTENT:")
        logger.info(f"  • Total items: {stats.multimodal_count}")
        logger.info(f"  • Ratio: {stats.multimodal_ratio:.1%}")
        
        if stats.multimodal_types:
            logger.info("  • Type distribution:")
            for modal_type, count in stats.multimodal_types.items():
                logger.info(f"    - {modal_type}: {count}")
        
        logger.info("\n🎯 PROCESSING RECOMMENDATION:")
        if analysis.should_use_multimodal_processing:
            logger.info("  ✅ Enable multimodal processing")
        else:
            logger.info("  📝 Text-only processing sufficient")
        
        logger.info("="*50)