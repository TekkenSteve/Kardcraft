"""MinerU Cloud API parser (clear, step-by-step version).

Design goal: readability first.
Main steps:
1) validate input + token
2) request upload URL
3) upload file
4) poll parse result
5) download and decode zip
6) build ParseResult
"""

import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult


class MinerUCloudAPIParser(BaseFileParser):
    """Parse documents via MinerU official cloud service."""

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
        self.api_base = str(
            params.get("api_base_url")
            or os.getenv("MINERU_CLOUD_API_URL")
            or "https://mineru.net/api/v4"
        ).rstrip("/")
        self.api_token = params.get("api_token") or os.getenv("MINERU_CLOUD_API_TOKEN")

        self.model_version = params.get("model_version") or os.getenv(
            "MINERU_CLOUD_MODEL_VERSION", "vlm"
        )
        self.poll_interval = float(
            params.get("poll_interval")
            or os.getenv("MINERU_CLOUD_POLL_INTERVAL", "3")
        )
        self.timeout = int(params.get("timeout") or os.getenv("MINERU_CLOUD_TIMEOUT", "1800"))

        # Optional parse controls
        self.is_ocr = params.get("is_ocr")
        self.enable_formula = params.get("enable_formula")
        self.enable_table = params.get("enable_table")
        self.language = params.get("language")
        self.page_ranges = params.get("page_ranges")
        self.data_id = params.get("data_id")

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    def check_health(self) -> Dict[str, Any]:
        """Best-effort health check for token + endpoint reachability."""
        if not self.api_token:
            return {
                "status": "unhealthy",
                "message": "MINERU_CLOUD_API_TOKEN is missing",
                "details": {"api_base": self.api_base},
            }

        test_data = {
            "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
            "model_version": "vlm",
        }

        try:
            response = requests.post(
                f"{self.api_base}/extract/task",
                headers=self._headers(),
                json=test_data,
                timeout=10,
            )
            if response.status_code == 401:
                return {
                    "status": "unhealthy",
                    "message": "API token invalid or expired",
                    "details": {"status_code": 401},
                }
            if response.status_code == 403:
                return {
                    "status": "unhealthy",
                    "message": "API token permission denied",
                    "details": {"status_code": 403},
                }
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "MinerU cloud API reachable",
                    "details": {"api_base": self.api_base},
                }
            return {
                "status": "unhealthy",
                "message": f"HTTP {response.status_code}",
                "details": {"status_code": response.status_code},
            }
        except requests.exceptions.Timeout:
            return {"status": "timeout", "message": "health check timeout", "details": {}}
        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "cannot connect to MinerU cloud API",
                "details": {"api_base": self.api_base},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"health check failed: {e}",
                "details": {},
            }

    async def parse(self, file_path: str) -> ParseResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        if not self.api_token:
            raise RuntimeError("MINERU_CLOUD_API_TOKEN is required")

        batch_id, upload_url = self._request_upload_url(file_path)
        self._upload_file(upload_url, file_path)
        result = self._poll_batch_result(batch_id)

        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("MinerU cloud response missing full_zip_url")

        zip_bytes = self._download_zip(zip_url)
        content_list, markdown = self._decode_zip(zip_bytes)

        metadata = self._get_file_metadata(file_path)
        metadata.update(
            {
                "parser": "mineru_cloud_api",
                "api_base": self.api_base,
                "model_version": self.model_version,
                "batch_id": batch_id,
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

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }

    def _request_upload_url(self, file_path: str) -> Tuple[str, str]:
        filename = os.path.basename(file_path)

        file_item: Dict[str, Any] = {"name": filename}
        if self.is_ocr is not None:
            file_item["is_ocr"] = bool(self.is_ocr)
        if self.data_id:
            file_item["data_id"] = self.data_id
        if self.page_ranges:
            file_item["page_ranges"] = self.page_ranges

        body: Dict[str, Any] = {
            "files": [file_item],
            "model_version": self.model_version,
        }
        if self.enable_formula is not None:
            body["enable_formula"] = bool(self.enable_formula)
        if self.enable_table is not None:
            body["enable_table"] = bool(self.enable_table)
        if self.language:
            body["language"] = self.language

        response = requests.post(
            f"{self.api_base}/file-urls/batch",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        if payload.get("code") not in (0, "0"):
            raise RuntimeError(f"upload-url failed: {payload}")

        data = payload.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise RuntimeError(f"upload-url response missing fields: {payload}")

        return str(batch_id), str(file_urls[0])

    def _upload_file(self, upload_url: str, file_path: str) -> None:
        with open(file_path, "rb") as f:
            response = requests.put(upload_url, data=f, timeout=60)
        if response.status_code != 200:
            raise RuntimeError(f"file upload failed: HTTP {response.status_code}")

    def _poll_batch_result(self, batch_id: str) -> Dict[str, Any]:
        started = time.time()
        status_url = f"{self.api_base}/extract-results/batch/{batch_id}"

        while True:
            if time.time() - started > self.timeout:
                raise RuntimeError("cloud parse timeout")

            response = requests.get(status_url, headers=self._headers(), timeout=30)
            response.raise_for_status()
            payload = response.json()

            if payload.get("code") not in (0, "0"):
                raise RuntimeError(f"status query failed: {payload}")

            extract_results = (payload.get("data") or {}).get("extract_result") or []
            if not extract_results:
                time.sleep(self.poll_interval)
                continue

            first = extract_results[0]
            state = first.get("state")
            if state == "done":
                return first
            if state == "failed":
                raise RuntimeError(f"parse failed: {first.get('err_msg') or 'unknown'}")

            time.sleep(self.poll_interval)

    @staticmethod
    def _download_zip(zip_url: str) -> bytes:
        response = requests.get(zip_url, timeout=60)
        response.raise_for_status()
        return response.content

    @staticmethod
    def _decode_zip(zip_bytes: bytes) -> Tuple[List[Dict[str, Any]], str]:
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
