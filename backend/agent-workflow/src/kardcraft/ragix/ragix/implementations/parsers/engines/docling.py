# implementations/parsers/docling.py - Docling 文档解析器
"""
Docling 文档解析器

基于 RAGAnything 的 Docling Parser 实现
支持 PDF、Office 文档和 HTML 文件的解析
"""

import os
import json
import subprocess
import base64
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class DoclingParser(BaseFileParser):
    """Docling 文档解析器"""

    OFFICE_FORMATS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
    HTML_FORMATS = {".html", ".htm", ".xhtml"}

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".ppt",
            ".pptx",
            ".xls",
            ".xlsx",
            ".html",
            ".htm",
            ".xhtml",
        ]
        self._parse_method = config.params.get("parse_method", "auto")
        self._lang = config.params.get("lang", "Chinese")

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        """解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()

        if file_ext == ".pdf":
            return await self._parse_pdf(file_path)
        elif file_ext in self.OFFICE_FORMATS:
            return await self._parse_office(file_path)
        elif file_ext in self.HTML_FORMATS:
            return await self._parse_html(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

    async def _parse_pdf(self, pdf_path: str) -> ParseResult:
        """使用 Docling 解析 PDF"""
        try:
            content_list, md_content = await self._run_docling(pdf_path)

            multimodal_items = self._extract_multimodal_items(content_list)
            text_content = self._merge_text_content(content_list)

            entities, relations = self._extract_entities_and_relations(content_list)

            metadata = self._get_file_metadata(pdf_path)
            metadata.update(
                {
                    "parser": "docling",
                    "parse_method": self._parse_method,
                    "content_items": len(content_list),
                    "multimodal_items": len(multimodal_items),
                }
            )

            document_structure = self._build_document_structure_from_content_list(
                content_list, metadata
            )

            doc_id = self._generate_doc_id(pdf_path, text_content)

            return ParseResult(
                doc_id=doc_id,
                content=text_content,
                metadata=metadata,
                multimodal_items=multimodal_items,
                content_list=content_list,
                entities=entities,
                relations=relations,
                document_structure=document_structure,
            )

        except Exception as e:
            logger.error(f"Docling PDF parsing failed: {e}")
            raise

    async def _parse_office(self, doc_path: str) -> ParseResult:
        """使用 Docling 解析 Office 文档"""
        try:
            content_list, md_content = await self._run_docling(doc_path)

            multimodal_items = self._extract_multimodal_items(content_list)
            text_content = self._merge_text_content(content_list)

            entities, relations = self._extract_entities_and_relations(content_list)

            metadata = self._get_file_metadata(doc_path)
            metadata.update(
                {
                    "parser": "docling",
                    "parse_method": self._parse_method,
                    "content_items": len(content_list),
                    "multimodal_items": len(multimodal_items),
                }
            )

            document_structure = self._build_document_structure_from_content_list(
                content_list, metadata
            )

            doc_id = self._generate_doc_id(doc_path, text_content)

            return ParseResult(
                doc_id=doc_id,
                content=text_content,
                metadata=metadata,
                multimodal_items=multimodal_items,
                content_list=content_list,
                entities=entities,
                relations=relations,
                document_structure=document_structure,
            )

        except Exception as e:
            logger.error(f"Docling Office parsing failed: {e}")
            raise

    async def _parse_html(self, html_path: str) -> ParseResult:
        """使用 Docling 解析 HTML"""
        try:
            content_list, md_content = await self._run_docling(html_path)

            multimodal_items = self._extract_multimodal_items(content_list)
            text_content = self._merge_text_content(content_list)

            entities, relations = self._extract_entities_and_relations(content_list)

            metadata = self._get_file_metadata(html_path)
            metadata.update(
                {
                    "parser": "docling",
                    "parse_method": self._parse_method,
                    "content_items": len(content_list),
                    "multimodal_items": len(multimodal_items),
                }
            )

            document_structure = self._build_document_structure_from_content_list(
                content_list, metadata
            )

            doc_id = self._generate_doc_id(html_path, text_content)

            return ParseResult(
                doc_id=doc_id,
                content=text_content,
                metadata=metadata,
                multimodal_items=multimodal_items,
                content_list=content_list,
                entities=entities,
                relations=relations,
                document_structure=document_structure,
            )

        except Exception as e:
            logger.error(f"Docling HTML parsing failed: {e}")
            raise

    async def _run_docling(self, input_path: str) -> Tuple[List[Dict], str]:
        """运行 Docling 命令"""
        input_path = Path(input_path)

        with tempfile.TemporaryDirectory() as output_dir:
            output_path = Path(output_dir)

            file_stem = input_path.stem
            file_output_dir = output_path / file_stem / "docling"
            file_output_dir.mkdir(parents=True, exist_ok=True)

            cmd_json = [
                "docling",
                "--output",
                str(file_output_dir),
                "--to",
                "json",
                str(input_path),
            ]

            cmd_md = [
                "docling",
                "--output",
                str(file_output_dir),
                "--to",
                "md",
                str(input_path),
            ]

            logger.info(f"Running Docling: {' '.join(cmd_json)}")

            try:
                import platform

                subprocess_kwargs = {
                    "capture_output": True,
                    "text": True,
                    "check": True,
                    "encoding": "utf-8",
                    "errors": "ignore",
                }

                if platform.system() == "Windows":
                    subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

                subprocess.run(cmd_json, **subprocess_kwargs)
                subprocess.run(cmd_md, **subprocess_kwargs)

            except subprocess.CalledProcessError as e:
                logger.error(f"Error running docling: {e}")
                raise
            except FileNotFoundError:
                raise RuntimeError(
                    "docling command not found. Please ensure Docling is properly installed."
                )

            content_list, md_content = self._read_output_files(
                file_output_dir, file_stem
            )

            return content_list, md_content

    def _read_output_files(
        self, output_dir: Path, file_stem: str
    ) -> Tuple[List[Dict], str]:
        """读取 Docling 输出文件"""
        md_file = output_dir / f"{file_stem}.md"
        json_file = output_dir / f"{file_stem}.json"

        md_content = ""
        if md_file.exists():
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                logger.warning(f"Could not read markdown file: {e}")

        content_list = []
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    docling_content = json.load(f)
                    content_list = self._convert_from_docling(
                        docling_content.get("body", []),
                        "body",
                        output_dir,
                        0,
                        "0",
                        docling_content,
                    )
            except Exception as e:
                logger.warning(f"Could not read JSON file: {e}")

        return content_list, md_content

    def _convert_from_docling(
        self,
        block: Any,
        type: str,
        output_dir: Path,
        cnt: int,
        num: str,
        docling_content: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """将 Docling 格式转换为标准格式"""
        content_list = []

        if not block.get("children"):
            cnt += 1
            content_list.append(self._convert_block(block, type, output_dir, cnt, num))
        else:
            if type not in ["groups", "body"]:
                cnt += 1
                content_list.append(
                    self._convert_block(block, type, output_dir, cnt, num)
                )

            members = block.get("children", [])
            for member in members:
                cnt += 1
                member_tag = member.get("$ref", "")
                if not member_tag:
                    continue

                member_type = member_tag.split("/")[1] if "/" in member_tag else ""
                member_num = (
                    member_tag.split("/")[2] if len(member_tag.split("/")) > 2 else "0"
                )

                if member_type in docling_content:
                    try:
                        member_block = docling_content[member_type][int(member_num)]
                    except (ValueError, IndexError):
                        continue

                    content_list.extend(
                        self._convert_from_docling(
                            member_block,
                            member_type,
                            output_dir,
                            cnt,
                            member_num,
                            docling_content,
                        )
                    )

        return content_list

    def _convert_block(
        self, block: Dict, type: str, output_dir: Path, cnt: int, num: str
    ) -> Dict[str, Any]:
        """转换单个 Docling 块"""
        if type == "texts":
            label = block.get("label", "")
            if label == "formula":
                return {
                    "type": "equation",
                    "img_path": "",
                    "text": block.get("orig", ""),
                    "text_format": "unknown",
                    "page_idx": cnt // 10,
                }
            else:
                return {
                    "type": "text",
                    "text": block.get("orig", ""),
                    "page_idx": cnt // 10,
                }

        elif type == "pictures":
            try:
                image_uri = block.get("image", {}).get("uri", "")
                if "," in image_uri:
                    base64_str = image_uri.split(",")[1]
                    image_dir = output_dir / "images"
                    image_dir.mkdir(parents=True, exist_ok=True)
                    image_path = image_dir / f"image_{num}.png"

                    with open(image_path, "wb") as f:
                        f.write(base64.b64decode(base64_str))

                    return {
                        "type": "image",
                        "img_path": str(image_path.resolve()),
                        "img_caption": block.get("caption", []),
                        "img_footnote": block.get("footnote", []),
                        "page_idx": cnt // 10,
                    }
            except Exception as e:
                logger.warning(f"Failed to process image {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Image: {block.get('caption', '')}]",
                    "page_idx": cnt // 10,
                }

        else:
            try:
                table_data = block.get("data", [])
                if isinstance(table_data, list):
                    table_body = "\n".join(["|".join(row) for row in table_data])
                else:
                    table_body = str(table_data)

                return {
                    "type": "table",
                    "img_path": "",
                    "table_caption": block.get("caption", []),
                    "table_footnote": block.get("footnote", []),
                    "table_body": table_body,
                    "page_idx": cnt // 10,
                }
            except Exception as e:
                logger.warning(f"Failed to process table {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Table: {block.get('caption', '')}]",
                    "page_idx": cnt // 10,
                }

    def _extract_multimodal_items(self, content_list: List[Dict]) -> List[Dict]:
        """从内容列表中提取多模态元素"""
        multimodal_items = []

        for idx, item in enumerate(content_list):
            item_type = item.get("type", "")

            if item_type == "image":
                multimodal_items.append(
                    {
                        "type": "image",
                        "content": item.get("img_path", ""),
                        "image_caption": item.get("img_caption", []),
                        "image_footnote": item.get("img_footnote", []),
                        "page_idx": item.get("page_idx", 0),
                        "index": idx,
                        "metadata": item,
                    }
                )

            elif item_type == "table":
                multimodal_items.append(
                    {
                        "type": "table",
                        "content": item.get("table_body", ""),
                        "table_caption": item.get("table_caption", []),
                        "table_footnote": item.get("table_footnote", []),
                        "page_idx": item.get("page_idx", 0),
                        "index": idx,
                        "metadata": item,
                    }
                )

            elif item_type == "equation":
                multimodal_items.append(
                    {
                        "type": "equation",
                        "content": item.get("latex", item.get("text", "")),
                        "text": item.get("text", ""),
                        "page_idx": item.get("page_idx", 0),
                        "index": idx,
                        "metadata": item,
                    }
                )

        return multimodal_items

    def _merge_text_content(self, content_list: List[Dict]) -> str:
        """合并所有文本内容"""
        text_parts = []

        for item in content_list:
            item_type = item.get("type", "")

            if item_type == "text":
                text = item.get("text", "")
                if text:
                    text_parts.append(text)

            elif item_type == "image":
                captions = item.get("img_caption", [])
                if captions:
                    text_parts.append(
                        " ".join(captions)
                        if isinstance(captions, list)
                        else str(captions)
                    )

            elif item_type == "table":
                caption = item.get("table_caption", [])
                if caption:
                    text_parts.append(
                        " ".join(caption) if isinstance(caption, list) else str(caption)
                    )
                table_body = item.get("table_body", "")
                if table_body:
                    text_parts.append(str(table_body))

            elif item_type == "equation":
                text = item.get("text", "")
                if text:
                    text_parts.append(text)

        return "\n\n".join(text_parts)

    def _extract_entities_and_relations(
        self, content_list: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """提取实体和关系"""
        entities = []
        relations = []

        for idx, item in enumerate(content_list):
            item_type = item.get("type", "")

            if item_type == "image" and item.get("img_caption"):
                entity_name = f"image_{idx}"
                caption = item.get("img_caption", [])
                description = (
                    " ".join(caption) if isinstance(caption, list) else str(caption)
                )
                entities.append(
                    {
                        "entity_name": entity_name,
                        "entity_type": "image",
                        "description": description,
                        "page_idx": item.get("page_idx", 0),
                    }
                )

            elif item_type == "table" and item.get("table_caption"):
                entity_name = f"table_{idx}"
                caption = item.get("table_caption", [])
                description = (
                    " ".join(caption) if isinstance(caption, list) else str(caption)
                )
                entities.append(
                    {
                        "entity_name": entity_name,
                        "entity_type": "table",
                        "description": description,
                        "page_idx": item.get("page_idx", 0),
                    }
                )

            elif item_type == "equation" and item.get("text"):
                entity_name = f"equation_{idx}"
                entities.append(
                    {
                        "entity_name": entity_name,
                        "entity_type": "equation",
                        "description": item.get("text", ""),
                        "latex": item.get("latex", ""),
                        "page_idx": item.get("page_idx", 0),
                    }
                )

        return entities, relations

    def _build_document_structure_from_content_list(
        self, content_list: List[Dict], metadata: Dict
    ):
        """从内容列表构建文档结构"""
        from ....protocols.context_extractors import DocumentStructure

        elements = []

        for idx, item in enumerate(content_list):
            item_type = item.get("type", "text")

            element = {
                "id": f"element_{idx}",
                "type": item_type,
                "page_idx": item.get("page_idx", 0),
                "index": idx,
                "content": item.get("text", "")
                or item.get("img_caption", [])
                or item.get("table_caption", []),
            }

            elements.append(element)

        element_index_map = {elem["id"]: idx for idx, elem in enumerate(elements)}

        return DocumentStructure(
            elements=elements, metadata=metadata, element_index_map=element_index_map
        )

    @classmethod
    def check_installation(cls) -> bool:
        """检查 Docling 是否正确安装"""
        try:
            result = subprocess.run(
                ["docling", "--version"], capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
