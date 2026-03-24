# implementations/preprocessors/document_pipeline.py
"""
Document preprocessing pipeline (LightRAG Server mode).

Parse files into text/structured content before sending to LightRAG.
Best-effort: if parsing fails, caller should fall back to raw upload.
"""

import hashlib
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from ...protocols.parsers import ParserConfig, ParseResult
from ...utils.cache import Cache
from ...utils.cache_config import get_cache_ttl
from ...implementations.parsers.smart import SmartParser
from kardcraft.utils.logger import logger


@dataclass
class PreprocessConfig:
    emit_original: bool = True
    emit_metadata: bool = True
    context_window: int = 1


class DocumentPipeline:
    """Preprocess documents using existing parsers (SmartParser)."""

    def __init__(self, config: PreprocessConfig):
        self.config = config
        self._parser = SmartParser(ParserConfig(name="document_pipeline"))
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._parser.initialize()
        self._initialized = True

    async def preprocess(
        self,
        file_path: str,
        parser_override: Optional[str] = None,
        parse_method_override: Optional[str] = None,
        parser_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return a list of text payloads for insertion."""
        if not self._initialized:
            await self.initialize()

        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)

        if (
            parser_override is None
            and self._parser.choose_parser_strategy(file_path) == "lightrag_native"
        ):
            logger.info("Use LightRAG native parsing for simple format")
            return []

        if parser_override:
            parser = SmartParser(
                ParserConfig(
                    name=f"document_pipeline_{parser_override}",
                    params={
                        "parser_override": parser_override,
                        "parse_method_override": parse_method_override,
                        "parser_params": parser_params or {},
                    },
                )
            )
            await parser.initialize()
        else:
            parser = self._parser
        cache_key = self._build_cache_key(file_path, parser)
        cached = None
        try:
            cached = await Cache.get(cache_key, category="result")
        except Exception as e:
            logger.warning(f"Failed to read parse cache: {e}")

        if cached:
            result = self._from_cached(cached)
        else:
            result = await parser.parse(file_path)
            try:
                await Cache.set(
                    cache_key,
                    self._to_cached(result),
                    category="result",
                    ttl=get_cache_ttl("parse_result"),
                )
            except Exception as e:
                logger.warning(f"Failed to write parse cache: {e}")

        return self._build_payloads(result)

    def _build_payloads(self, result: ParseResult) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        content = (result.content or "").strip()
        doc_id = self._generate_doc_id(
            content,
            result.metadata,
            result.multimodal_items,
            result.content_list,
        )
        logger.info(f"Generated doc_id: {doc_id}")

        if not content:
            logger.warning("Parser produced empty text content; skip metadata-only insertion")
            return []

        payloads.append(
            {
                "content": content,
                "file_source": result.metadata.get("file_name"),
            }
        )

        if self.config.emit_metadata and result.metadata:
            meta_lines = [f"{k}: {v}" for k, v in result.metadata.items()]
            payloads.append(
                {
                    "content": "Document Metadata\n" + "\n".join(meta_lines),
                    "file_source": result.metadata.get("file_name"),
                }
            )

        # Best-effort multimodal context enrichment
        for item in result.multimodal_items or []:
            context = self._extract_context(result, item)
            modal_text = self._render_modal_item(item, context)
            if not modal_text:
                continue
            payloads.append(
                {
                    "content": modal_text,
                    "file_source": result.metadata.get("file_name"),
                }
            )

        if not payloads:
            logger.warning("Preprocess produced empty content")
        return payloads

    def _build_cache_key(self, file_path: str, parser: Any) -> str:
        stat = os.stat(file_path)
        parser_name = parser.get_name()
        config = parser.get_config()
        key_material = f"{file_path}:{stat.st_mtime}:{parser_name}:{getattr(config, 'strategy', '')}"
        return hashlib.md5(key_material.encode()).hexdigest()

    def _to_cached(self, result: ParseResult) -> Dict[str, Any]:
        return {
            "doc_id": result.doc_id,
            "content": result.content,
            "metadata": result.metadata,
            "multimodal_items": result.multimodal_items,
            "content_list": result.content_list,
            "entities": result.entities,
            "relations": result.relations,
        }

    def _from_cached(self, data: Dict[str, Any]) -> ParseResult:
        return ParseResult(
            doc_id=data.get("doc_id", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}) or {},
            multimodal_items=data.get("multimodal_items", []) or [],
            content_list=data.get("content_list", []) or [],
            entities=data.get("entities", []) or [],
            relations=data.get("relations", []) or [],
            document_structure=None,
        )


    def _generate_doc_id(
        self,
        content: str,
        metadata: Dict[str, Any],
        multimodal_items: Optional[List[Dict[str, Any]]] = None,
        content_list: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        base = content.strip()
        if not base:
            base = f"{metadata.get('file_name','')}-{metadata.get('file_size','')}"
        signature = self._build_content_signature(content_list, multimodal_items)
        if signature:
            base = base + "\n" + signature
        return "doc_" + hashlib.md5(base.encode()).hexdigest()[:12]

    def _build_content_signature(
        self,
        content_list: Optional[List[Dict[str, Any]]],
        multimodal_items: Optional[List[Dict[str, Any]]],
    ) -> str:
        fragments: List[str] = []

        def _append(item_type: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, list):
                value = " ".join([str(v) for v in value if v])
            value = str(value).strip()
            if value:
                fragments.append(f"{item_type}:{value}")

        if content_list:
            for item in content_list:
                t = str(item.get("type", "text"))
                if t == "text":
                    _append(t, item.get("text"))
                elif t == "image":
                    _append(t, item.get("img_path") or item.get("img_caption"))
                elif t == "table":
                    _append(t, item.get("table_body") or item.get("table_caption"))
                elif t == "equation":
                    _append(t, item.get("latex") or item.get("text"))
                else:
                    _append(t, item)
        elif multimodal_items:
            for item in multimodal_items:
                t = str(item.get("type", "modal"))
                _append(t, item.get("content") or item.get("text") or item)

        return "\n".join(fragments)

    def _extract_context(self, result: ParseResult, item: Dict[str, Any]) -> str:
        # Use document_structure if available; otherwise fallback to empty.
        structure = result.document_structure
        if not structure or not getattr(structure, "elements", None):
            return ""
        index = item.get("index")
        if index is None:
            return ""
        elements = structure.elements
        start = max(0, index - self.config.context_window)
        end = min(len(elements), index + self.config.context_window + 1)
        texts = []
        for i in range(start, end):
            text = elements[i].get("content")
            if text:
                texts.append(text)
        return "\n".join(texts).strip()

    def _render_modal_item(self, item: Dict[str, Any], context: str) -> Optional[str]:
        t = item.get("type")
        page_idx = item.get("page_idx")
        content = item.get("content") or item.get("text")

        def _join(value) -> str:
            if not value:
                return ""
            if isinstance(value, list):
                return " ".join([str(v) for v in value if v])
            return str(value)

        if t == "image":
            caption = _join(item.get("image_caption"))
            footnote = _join(item.get("image_footnote"))
            return self._format_modal_block(
                modal_type="Image",
                page_idx=page_idx,
                context=context,
                content=content,
                caption=caption,
                footnote=footnote,
            )

        if t == "table":
            caption = _join(item.get("table_caption"))
            footnote = _join(item.get("table_footnote"))
            return self._format_modal_block(
                modal_type="Table",
                page_idx=page_idx,
                context=context,
                content=content,
                caption=caption,
                footnote=footnote,
            )

        if t == "equation":
            return self._format_modal_block(
                modal_type="Equation",
                page_idx=page_idx,
                context=context,
                content=content,
            )

        if content:
            return self._format_modal_block(
                modal_type=t or "Modal",
                page_idx=page_idx,
                context=context,
                content=content,
            )
        return None

    def _format_modal_block(
        self,
        *,
        modal_type: str,
        page_idx: Optional[int],
        context: str,
        content: Optional[str],
        caption: Optional[str] = None,
        footnote: Optional[str] = None,
    ) -> str:
        lines = [f"[{modal_type}]"]
        if page_idx is not None:
            lines.append(f"page: {page_idx}")
        if context:
            lines.append("context:")
            lines.append(context)
        if caption:
            lines.append("caption:")
            lines.append(caption)
        if footnote:
            lines.append("footnote:")
            lines.append(footnote)
        if content:
            lines.append("content:")
            lines.append(content)
        return "\n".join(lines).strip()
