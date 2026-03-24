# implementations/parsers/mineru.py - MinerU 文档解析器
"""
MinerU 文档解析器

基于 RAGAnything 的 MinerU Parser 实现
支持 PDF 和图像文档的解析，生成结构化内容和多模态元素
"""

import os
import json
import subprocess
import logging
import tempfile
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple
from queue import Queue, Empty

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class MinerUExecutionError(Exception):
    """MinerU 执行错误"""

    def __init__(self, return_code: int, error_msg: List[str]):
        self.return_code = return_code
        self.error_msg = error_msg
        super().__init__(
            f"MinerU command failed with return code {return_code}: {error_msg}"
        )


class MinerUParser(BaseFileParser):
    """MinerU 文档解析器"""

    OFFICE_FORMATS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
    IMAGE_FORMATS = {".png", ".jpeg", ".jpg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    TEXT_FORMATS = {".txt", ".md"}

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [
            ".pdf",
            ".png",
            ".jpeg",
            ".jpg",
            ".bmp",
            ".tiff",
            ".gif",
            ".webp",
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
        elif file_ext in self.IMAGE_FORMATS:
            return await self._parse_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

    async def _parse_pdf(self, pdf_path: str) -> ParseResult:
        """使用 MinerU 解析 PDF"""
        try:
            content_list, md_content = await self._run_mineru(pdf_path)

            # 转换为 ParseResult 格式
            multimodal_items = self._extract_multimodal_items(content_list)

            # 合并所有文本内容
            text_content = self._merge_text_content(content_list)

            # 构建实体和关系
            entities, relations = self._extract_entities_and_relations(content_list)

            # 元数据
            metadata = self._get_file_metadata(pdf_path)
            metadata.update(
                {
                    "parser": "mineru",
                    "parse_method": self._parse_method,
                    "content_items": len(content_list),
                    "multimodal_items": len(multimodal_items),
                }
            )

            # 文档结构
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
            logger.error(f"MinerU PDF parsing failed: {e}")
            raise

    async def _parse_image(self, image_path: str) -> ParseResult:
        """使用 MinerU 解析图像"""
        try:
            content_list, md_content = await self._run_mineru(image_path)

            multimodal_items = self._extract_multimodal_items(content_list)
            text_content = self._merge_text_content(content_list)

            entities, relations = self._extract_entities_and_relations(content_list)

            metadata = self._get_file_metadata(image_path)
            metadata.update(
                {
                    "parser": "mineru",
                    "parse_method": self._parse_method,
                    "content_items": len(content_list),
                    "multimodal_items": len(multimodal_items),
                }
            )

            document_structure = self._build_document_structure_from_content_list(
                content_list, metadata
            )

            doc_id = self._generate_doc_id(image_path, text_content)

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
            logger.error(f"MinerU image parsing failed: {e}")
            raise

    async def _run_mineru(self, input_path: str) -> Tuple[List[Dict], str]:
        """运行 MinerU 命令"""
        input_path = Path(input_path)

        # 创建临时输出目录
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = Path(output_dir)

            # 构建命令
            cmd = [
                "mineru",
                "-p",
                str(input_path),
                "-o",
                str(output_path),
                "-m",
                self._parse_method,
            ]

            if self._lang:
                cmd.extend(["-l", self._lang])

            logger.info(f"Running MinerU: {' '.join(cmd)}")

            # 执行命令
            self._execute_command(cmd)

            # 读取输出
            content_list, md_content = self._read_output_files(
                output_path, input_path.stem
            )

            return content_list, md_content

    def _execute_command(self, cmd: List[str]) -> None:
        """执行命令并实时输出"""
        try:
            import platform

            subprocess_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "ignore",
                "bufsize": 1,
            }

            if platform.system() == "Windows":
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            def enqueue_output(pipe, queue, prefix):
                try:
                    for line in iter(pipe.readline, ""):
                        if line.strip():
                            queue.put((prefix, line.strip()))
                    pipe.close()
                except Exception as e:
                    queue.put((prefix, f"Error: {e}"))

            process = subprocess.Popen(cmd, **subprocess_kwargs)
            stdout_queue = Queue()
            stderr_queue = Queue()

            stdout_thread = threading.Thread(
                target=enqueue_output, args=(process.stdout, stdout_queue, "STDOUT")
            )
            stderr_thread = threading.Thread(
                target=enqueue_output, args=(process.stderr, stderr_queue, "STDERR")
            )

            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            error_lines = []
            while process.poll() is None:
                try:
                    while True:
                        prefix, line = stdout_queue.get_nowait()
                        logger.info(f"[MinerU] {line}")
                except Empty:
                    pass

                try:
                    while True:
                        prefix, line = stderr_queue.get_nowait()
                        if "error" in line.lower():
                            error_lines.append(line)
                        logger.warning(f"[MinerU] {line}")
                except Empty:
                    pass

                import time

                time.sleep(0.1)

            return_code = process.wait()

            if return_code != 0 or error_lines:
                raise MinerUExecutionError(return_code, error_lines)

        except MinerUExecutionError:
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "mineru command not found. Please ensure MinerU 2.0 is properly installed:\n"
                "pip install -U 'mineru[core]' or uv pip install -U 'mineru[core]'"
            )
        except Exception as e:
            raise RuntimeError(f"Error running mineru: {e}")

    def _read_output_files(
        self, output_dir: str, file_stem: str
    ) -> Tuple[List[Dict], str]:
        """读取 MinerU 输出文件"""
        output_path = Path(output_dir)

        md_file = output_path / f"{file_stem}.md"
        json_file = output_path / f"{file_stem}_content_list.json"
        images_base_dir = output_path

        file_stem_subdir = output_path / file_stem
        if file_stem_subdir.is_dir():
            for subdir in file_stem_subdir.iterdir():
                if not subdir.is_dir():
                    continue
                candidate_json = subdir / f"{file_stem}_content_list.json"
                if candidate_json.exists():
                    md_file = subdir / f"{file_stem}.md"
                    json_file = candidate_json
                    images_base_dir = subdir
                    break

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
                    content_list = json.load(f)

                # 修复相对路径
                for item in content_list:
                    if isinstance(item, dict):
                        for field_name in [
                            "img_path",
                            "table_img_path",
                            "equation_img_path",
                        ]:
                            if field_name in item and item[field_name]:
                                img_path = item[field_name]
                                absolute_img_path = (
                                    images_base_dir / img_path
                                ).resolve()
                                item[field_name] = str(absolute_img_path)

            except Exception as e:
                logger.warning(f"Could not read JSON file: {e}")

        return content_list, md_content

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
                table_body = item.get("table_body", "")
                if isinstance(table_body, list):
                    table_body = "\n".join(table_body)
                multimodal_items.append(
                    {
                        "type": "table",
                        "content": table_body,
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
                        "content": item.get("latex", ""),
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
                    text_parts.append(" ".join(captions))

            elif item_type == "table":
                caption = item.get("table_caption", [])
                if caption:
                    text_parts.append(" ".join(caption))
                table_body = item.get("table_body", "")
                if table_body:
                    if isinstance(table_body, list):
                        text_parts.append("\n".join(table_body))
                    else:
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
                entities.append(
                    {
                        "entity_name": entity_name,
                        "entity_type": "image",
                        "description": " ".join(item.get("img_caption", [])),
                        "page_idx": item.get("page_idx", 0),
                    }
                )

            elif item_type == "table" and item.get("table_caption"):
                entity_name = f"table_{idx}"
                entities.append(
                    {
                        "entity_name": entity_name,
                        "entity_type": "table",
                        "description": " ".join(item.get("table_caption", [])),
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
        from ...protocols.context_extractors import DocumentStructure

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
        """检查 MinerU 是否正确安装"""
        try:
            result = subprocess.run(
                ["mineru", "--version"], capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
