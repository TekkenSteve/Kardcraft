"""Minimal MinerU HTTP API parser.

Goal: keep the flow obvious.
1) upload file to MinerU API
2) read markdown/content_list from response
3) return ParseResult
"""

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult


class MinerUAPIParser(BaseFileParser):
    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".webp",
            ".gif",
            ".jp2"
        ]

        params = config.params or {}
        self.server_url = str(params.get("server_url") or os.getenv("MINERU_API_URI") or "http://localhost:8000").rstrip("/")
        self.endpoint = f"{self.server_url}/file_parse"
        self.timeout = int(params.get("timeout") or os.getenv("MINERU_TIMEOUT", "1800"))
        self.parse_method = params.get("parse_method", "auto")
        self.lang_list = params.get("lang_list", ["ch"])
        self.backend = params.get("backend", "pipeline")

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        response = self._request_parse(file_path)
        content_list, markdown = self._decode_response(response)

        metadata = self._get_file_metadata(file_path)
        metadata.update(
            {
                "parser": "mineru_api",
                "server_url": self.server_url,
                "parse_method": self.parse_method,
                "content_items": len(content_list),
            }
        )

        return ParseResult(
            doc_id=self._generate_doc_id(file_path, markdown),
            content=markdown,
            metadata=metadata,
            multimodal_items=self._extract_multimodal_items(content_list),
            content_list=content_list,
            entities=[],
            relations=[],
            document_structure=self._build_document_structure(markdown, metadata),
        )

    def _request_parse(self, file_path: str) -> requests.Response:
        data = {
            "parse_method": self.parse_method,
            "lang_list": self.lang_list,
            "backend": self.backend,
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }

        with open(file_path, "rb") as f:
            response = requests.post(
                self.endpoint,
                files={"files": (Path(file_path).name, f, "application/octet-stream")},
                data=data,
                timeout=self.timeout,
            )

        if response.status_code != 200:
            raise RuntimeError(f"MinerU API error ({response.status_code}): {response.text}")
        return response

    def _decode_response(self, response: requests.Response) -> Tuple[List[Dict[str, Any]], str]:
        # Main path: zip payload with *_content_list.json + *.md
        try:
            return self._decode_zip(response.content)
        except zipfile.BadZipFile:
            pass

        # Fallback: JSON payload
        try:
            payload = response.json()
            content_list = payload.get("content_list") or payload.get("items") or []
            markdown = str(payload.get("markdown") or payload.get("md") or payload.get("content") or "")
            return (content_list if isinstance(content_list, list) else []), markdown
        except Exception:
            return [], response.text or ""

    def _decode_zip(self, zip_bytes: bytes) -> Tuple[List[Dict[str, Any]], str]:
        content_list: List[Dict[str, Any]] = []
        markdown = ""

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for name in zf.namelist():
                if name.endswith("_content_list.json"):
                    with zf.open(name) as f:
                        loaded = json.loads(f.read().decode("utf-8", errors="ignore"))
                        if isinstance(loaded, list):
                            content_list = loaded
                elif name.endswith(".md") and not markdown:
                    with zf.open(name) as f:
                        markdown = f.read().decode("utf-8", errors="ignore")

        return content_list, markdown

    @staticmethod
    def _extract_multimodal_items(content_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for idx, item in enumerate(content_list):
            item_type = item.get("type")
            if item_type == "image":
                items.append(
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
                items.append(
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
                items.append(
                    {
                        "type": "equation",
                        "content": item.get("latex", ""),
                        "text": item.get("text", ""),
                        "page_idx": item.get("page_idx", 0),
                        "index": idx,
                        "metadata": item,
                    }
                )
        return items
