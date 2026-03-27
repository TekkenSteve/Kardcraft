"""DeepSeek OCR parser (SiliconFlow endpoint).

"""

import base64
import os
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class DSSeekMode(str, Enum):
    FREE_OCR = "free_ocr"
    GROUNDING = "grounding"


class DeepSeekOCRParser(BaseFileParser):
    MIME_TYPE_MAP = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = list(self.MIME_TYPE_MAP.keys())

        params = config.params or {}
        self.api_key = params.get("api_key") or os.getenv("SILICONFLOW_API_KEY")
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY is not set")

        self.api_url = params.get("api_url") or os.getenv(
            "SILICONFLOW_API_URL", "https://api.siliconflow.cn/v1/chat/completions"
        )
        self.model = params.get("model", "deepseek-ai/DeepSeek-OCR")
        self.timeout = int(params.get("timeout", 120))
        self.max_tokens = int(params.get("max_tokens", 4096))
        self.temperature = float(params.get("temperature", 0.1))

        self.mode = DSSeekMode(str(params.get("mode", DSSeekMode.FREE_OCR.value)))
        self.fallback_enabled = bool(params.get("fallback_enabled", True))
        self.fallback_mode = DSSeekMode(
            str(params.get("fallback_mode", DSSeekMode.GROUNDING.value))
        )
        self.min_output_threshold = int(params.get("min_output_threshold", 500))
        self.chinese_hint = bool(params.get("chinese_hint", False))

        self.pdf_dpi = int(params.get("pdf_dpi", 200))
        self.max_pdf_pages = int(params.get("max_pdf_pages", 0))  # 0 = no limit

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        started = time.time()
        if file_ext == ".pdf":
            content = self._process_pdf(file_path)
        else:
            content = self._process_image(file_path)

        elapsed = time.time() - started
        logger.info(
            f"DeepSeekOCR done: {Path(file_path).name} - {len(content)} chars ({elapsed:.2f}s)"
        )

        metadata = self._get_file_metadata(file_path)
        metadata.update(
            {
                "parser": "deepseek_ocr",
                "model": self.model,
                "api_url": self.api_url,
                "mode": self.mode.value,
            }
        )

        return ParseResult(
            doc_id=self._generate_doc_id(file_path, content),
            content=content,
            metadata=metadata,
            multimodal_items=[],
            entities=[],
            relations=[],
            document_structure=self._build_document_structure(content, metadata),
        )

    def _process_pdf(self, pdf_path: str) -> str:
        try:
            import fitz
        except Exception as e:
            raise RuntimeError("PyMuPDF (fitz) is required for PDF OCR") from e

        doc = fitz.open(pdf_path)
        try:
            total_pages = len(doc)
            if self.max_pdf_pages > 0:
                total_pages = min(total_pages, self.max_pdf_pages)

            chunks: List[str] = []
            for i in range(total_pages):
                page = doc[i]
                pix = page.get_pixmap(dpi=self.pdf_dpi)
                page_text = self._ocr_image_bytes(pix.tobytes("png"), "image/png")
                if page_text.strip():
                    chunks.append(page_text.strip())
            return "\n\n".join(chunks)
        finally:
            doc.close()

    def _process_image(self, image_path: str) -> str:
        mime_type = self._get_mime_type(image_path)
        with open(image_path, "rb") as f:
            return self._ocr_image_bytes(f.read(), mime_type)

    def _ocr_image_bytes(self, data_bytes: bytes, mime_type: str) -> str:
        primary = self._call_api(data_bytes, mime_type, self.mode)
        primary = self._post_process(primary)

        if (
            self.fallback_enabled
            and self.mode == DSSeekMode.FREE_OCR
            and len(primary.strip()) < self.min_output_threshold
        ):
            logger.warning(
                f"DeepSeekOCR fallback: output {len(primary.strip())} < {self.min_output_threshold}, "
                f"switch to {self.fallback_mode.value}"
            )
            secondary = self._call_api(data_bytes, mime_type, self.fallback_mode)
            return self._post_process(secondary)

        return primary

    def _build_prompt(self, mode: DSSeekMode) -> str:
        if mode == DSSeekMode.FREE_OCR:
            prompt = "Free OCR."
            if self.chinese_hint:
                prompt += " Please extract all text in Chinese and English."
            return prompt
        if mode == DSSeekMode.GROUNDING:
            return "<|grounding|>Convert the document to markdown."
        raise ValueError(f"Unsupported OCR mode: {mode}")

    def _call_api(self, data_bytes: bytes, mime_type: str, mode: DSSeekMode) -> str:
        data_url = f"data:{mime_type};base64,{base64.b64encode(data_bytes).decode('utf-8')}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self._build_prompt(mode)},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"DeepSeekOCR request failed: {e}") from e

        if response.status_code != 200:
            raise RuntimeError(f"DeepSeekOCR API error {response.status_code}: {response.text}")

        try:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"DeepSeekOCR response parse failed: {e}, body={response.text}") from e

    @staticmethod
    def _post_process(content: str) -> str:
        content = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "", content, flags=re.DOTALL)
        content = re.sub(r"<\|det\|>.*?<\|/det\|>", "", content, flags=re.DOTALL)
        return content.strip()

    def _get_mime_type(self, file_path: str) -> str:
        return self.MIME_TYPE_MAP.get(Path(file_path).suffix.lower(), "image/jpeg")

    def _build_document_structure(self, text: str, metadata: Dict[str, Any]) -> Any:
        from ....protocols.context_extractors import DocumentStructure

        elements = []
        for idx, para in enumerate(text.split("\n")):
            para = para.strip()
            if not para:
                continue
            elements.append(
                {
                    "id": f"paragraph_{idx}",
                    "type": "text",
                    "page_idx": 0,
                    "index": idx,
                    "content": para,
                }
            )

        element_index_map = {elem["id"]: i for i, elem in enumerate(elements)}
        return DocumentStructure(
            elements=elements,
            metadata=metadata,
            element_index_map=element_index_map,
        )

    def check_health(self) -> Dict[str, Any]:
        try:
            response = requests.get(
                "https://api.siliconflow.cn/v1/models",
                headers=self.headers,
                timeout=10,
            )
            if response.status_code == 200:
                return {"status": "healthy", "message": "DeepSeekOCR is available"}
            if response.status_code == 401:
                return {"status": "unhealthy", "message": "invalid API key"}
            return {
                "status": "unhealthy",
                "message": f"API error {response.status_code}",
            }
        except Exception as e:
            return {"status": "unavailable", "message": f"connection failed: {e}"}
