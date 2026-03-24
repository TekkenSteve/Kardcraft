# implementations/parsers/pdf.py - PDF文件解析器
"""
PDF文件解析器

支持.pdf文件的解析，支持多种解析方法：deepdoc、mineru、docling等
"""

import os
import subprocess
import tempfile
from pathlib import Path

from ...protocols.parsers import ParseResult
from .base import BaseFileParser


class PdfParser(BaseFileParser):
    """PDF文件解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [".pdf"]
        self._parse_method = config.params.get("parse_method", "deepdoc")
        self._lang = config.params.get("lang", "Chinese")

    async def parse(self, file_path: str) -> ParseResult:
        """解析PDF文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type for PdfParser: {file_ext}")

        if self._parse_method == "deepdoc":
            return await self._parse_with_deepdoc(file_path)
        if self._parse_method == "mineru":
            return await self._parse_with_mineru(file_path)
        if self._parse_method == "docling":
            return await self._parse_with_docling(file_path)

        return await self._parse_simple(file_path)

    async def _parse_simple(self, file_path: str) -> ParseResult:
        """简单PDF解析 - 优先 PyMuPDF，再回退 pdftotext。"""
        try:
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(file_path)
                pages = []
                for page in doc:
                    text = page.get_text("text") or ""
                    if text.strip():
                        pages.append(text.strip())
                doc.close()

                content = "\n\n".join(pages).strip()
                if content:
                    metadata = self._get_file_metadata(file_path)
                    metadata.update(
                        {
                            "parse_method": "simple",
                            "extraction_tool": "pymupdf",
                        }
                    )
                    doc_id = self._generate_doc_id(file_path, content)
                    document_structure = self._build_document_structure(content, metadata)
                    return ParseResult(
                        doc_id=doc_id,
                        content=content,
                        metadata=metadata,
                        multimodal_items=[],
                        entities=[],
                        relations=[],
                        document_structure=document_structure,
                    )
            except Exception:
                pass

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                subprocess.run(
                    ["pdftotext", "-layout", file_path, tmp_path],
                    check=True,
                    capture_output=True,
                )

                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()

                os.unlink(tmp_path)

                if not content:
                    return await self._fallback_parse(file_path)

                metadata = self._get_file_metadata(file_path)
                metadata.update(
                    {
                        "parse_method": "simple",
                        "extraction_tool": "pdftotext",
                    }
                )

                doc_id = self._generate_doc_id(file_path, content)
                document_structure = self._build_document_structure(content, metadata)

                return ParseResult(
                    doc_id=doc_id,
                    content=content,
                    metadata=metadata,
                    multimodal_items=[],
                    entities=[],
                    relations=[],
                    document_structure=document_structure,
                )

            except (subprocess.CalledProcessError, FileNotFoundError):
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return await self._fallback_parse(file_path)

        except Exception as e:
            raise ValueError(f"Simple PDF parsing failed: {e}")

    async def _parse_with_deepdoc(self, file_path: str) -> ParseResult:
        """使用DeepDoc解析PDF"""
        print("Warning: DeepDoc parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)

    async def _parse_with_mineru(self, file_path: str) -> ParseResult:
        """使用MinerU解析PDF"""
        print("Warning: MinerU parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)

    async def _parse_with_docling(self, file_path: str) -> ParseResult:
        """使用Docling解析PDF"""
        print("Warning: Docling parser not implemented, falling back to simple parsing")
        return await self._parse_simple(file_path)

    async def _fallback_parse(self, file_path: str) -> ParseResult:
        """回退解析：不产出伪正文，交由上游决定是否走原文件上传。"""
        try:
            with open(file_path, "rb") as f:
                binary_content = f.read()

            content = ""

            metadata = self._get_file_metadata(file_path)
            metadata.update(
                {
                    "parse_method": "fallback",
                    "warning": "PDF parsing fallback used; text extraction unavailable",
                    "raw_size_bytes": str(len(binary_content)),
                }
            )

            doc_id = self._generate_doc_id(file_path, content)
            document_structure = self._build_document_structure(content, metadata)

            return ParseResult(
                doc_id=doc_id,
                content=content,
                metadata=metadata,
                multimodal_items=[],
                entities=[],
                relations=[],
                document_structure=document_structure,
            )

        except Exception as e:
            raise ValueError(f"Fallback PDF parsing failed: {e}")
