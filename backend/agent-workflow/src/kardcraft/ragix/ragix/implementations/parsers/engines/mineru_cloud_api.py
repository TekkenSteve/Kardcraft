# implementations/parsers/engines/mineru_cloud_api.py - MinerU Cloud API 解析器
"""
MinerU Cloud API 解析器

基于 mineru 官方云端 API：
- 创建任务: POST /extract/task
- 查询任务: GET /extract/task/{task_id}
- 下载结果: full_zip_url

注意：该 API 仅支持 URL 输入，不支持直接上传文件。
"""

import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class MinerUCloudAPIParser(BaseFileParser):
    """MinerU Cloud API 解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".ppt",
            ".pptx",
            ".jpg",
            ".jpeg",
            ".png",
            ".html",
            ".htm",
        ]

        params = config.params or {}
        self.api_base_url = params.get("api_base_url") or os.getenv(
            "MINERU_CLOUD_API_URL", "https://mineru.net/api/v4"
        )
        self.api_token = params.get("api_token") or os.getenv("MINERU_CLOUD_API_TOKEN")
        self.model_version = params.get("model_version") or os.getenv(
            "MINERU_CLOUD_MODEL_VERSION", "vlm"
        )
        self.poll_interval = float(
            params.get("poll_interval")
            or os.getenv("MINERU_CLOUD_POLL_INTERVAL", "3")
        )
        self.timeout = int(
            params.get("timeout") or os.getenv("MINERU_CLOUD_TIMEOUT", "1800")
        )
        self.request_params = params.get("request_params") or {}

        # Official API optional params
        self.is_ocr = params.get("is_ocr")
        self.enable_formula = params.get("enable_formula")
        self.enable_table = params.get("enable_table")
        self.language = params.get("language")
        self.page_ranges = params.get("page_ranges")
        self.data_id = params.get("data_id")

    def check_health(self) -> dict:
        """检查 MinerU 云端 API 可用性与 token 有效性"""
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token or ''}",
        }
        test_body = {
            "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
            "model_version": "vlm",
        }
        try:
            res = requests.post(
                f"{self.api_base_url}/extract/task", headers=header, json=test_body, timeout=10
            )
            if res.status_code == 401:
                return {
                    "status": "unhealthy",
                    "message": "API token invalid or expired",
                    "details": {"status_code": 401},
                }
            if res.status_code == 403:
                return {
                    "status": "unhealthy",
                    "message": "API token permission denied",
                    "details": {"status_code": 403},
                }
            if res.status_code == 200:
                try:
                    payload = res.json()
                    if payload.get("code") == 0:
                        return {
                            "status": "healthy",
                            "message": "MinerU Cloud API reachable",
                            "details": {"api_base_url": self.api_base_url},
                        }
                    return {
                        "status": "unhealthy",
                        "message": f"API error: {payload.get('msg', 'unknown')}",
                        "details": {"code": payload.get("code")},
                    }
                except Exception:
                    return {
                        "status": "healthy",
                        "message": "MinerU Cloud API reachable",
                        "details": {"api_base_url": self.api_base_url},
                    }
            return {
                "status": "unhealthy",
                "message": f"API HTTP {res.status_code}",
                "details": {"status_code": res.status_code},
            }
        except requests.exceptions.Timeout:
            return {"status": "timeout", "message": "API request timeout", "details": {"timeout": "10s"}}
        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "Cannot connect to MinerU Cloud API",
                "details": {"api_base_url": self.api_base_url},
            }
        except Exception as e:
            return {"status": "error", "message": f"Health check failed: {e}", "details": {"error": str(e)}}

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        """使用 MinerU Cloud API 解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        if not self.api_token:
            raise RuntimeError(
                "MinerU Cloud API token is required. "
                "Set api_token in parser params or MINERU_CLOUD_API_TOKEN."
            )

        # HTML 需要指定模型版本
        model_version = self.model_version
        if file_ext in {".html", ".htm"} and model_version.lower() != "mineru-html":
            model_version = "MinerU-HTML"

        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        logger.info(f"MinerU Cloud API starting: {file_path}")

        try:
            # Step 1: request upload URL (batch)
            filename = os.path.basename(file_path)
            file_entry: Dict[str, Any] = {"name": filename}
            if self.is_ocr is not None:
                file_entry["is_ocr"] = bool(self.is_ocr)
            if self.page_ranges:
                file_entry["page_ranges"] = self.page_ranges
            if self.data_id:
                file_entry["data_id"] = self.data_id

            upload_body: Dict[str, Any] = {
                "files": [file_entry],
                "model_version": model_version,
                **self.request_params,
            }
            if self.enable_formula is not None:
                upload_body["enable_formula"] = bool(self.enable_formula)
            if self.enable_table is not None:
                upload_body["enable_table"] = bool(self.enable_table)
            if self.language:
                upload_body["language"] = self.language
            upload_url = f"{self.api_base_url}/file-urls/batch"
            res = requests.post(upload_url, headers=header, json=upload_body, timeout=30)
            res.raise_for_status()
            payload = res.json()
            if payload.get("code") not in (0, "0"):
                raise RuntimeError(f"MinerU upload URL failed: {payload}")
            batch_id = payload.get("data", {}).get("batch_id")
            file_urls = payload.get("data", {}).get("file_urls") or []
            if not batch_id or not file_urls:
                raise RuntimeError(f"MinerU upload URL missing data: {payload}")

            # Step 2: upload file
            with open(file_path, "rb") as f:
                put_res = requests.put(file_urls[0], data=f, timeout=60)
            if put_res.status_code != 200:
                raise RuntimeError(f"MinerU file upload failed: HTTP {put_res.status_code}")

            # Step 3: poll batch result
            task_url = f"{self.api_base_url}/extract-results/batch/{batch_id}"
            started = time.time()
            while True:
                if time.time() - started > self.timeout:
                    raise RuntimeError("MinerU batch task timeout")

                status_res = requests.get(task_url, headers=header, timeout=30)
                status_res.raise_for_status()
                status_payload = status_res.json()
                if status_payload.get("code") not in (0, "0"):
                    raise RuntimeError(f"MinerU status error: {status_payload}")
                extract_results = status_payload.get("data", {}).get("extract_result") or []
                if not extract_results:
                    time.sleep(self.poll_interval)
                    continue

                data_node = extract_results[0]
                state = data_node.get("state")

                if state == "done":
                    full_zip_url = data_node.get("full_zip_url")
                    if not full_zip_url:
                        raise RuntimeError(
                            f"MinerU completed but missing full_zip_url: {status_payload}"
                        )
                    break
                if state == "failed":
                    err_msg = data_node.get("err_msg") or "unknown error"
                    raise RuntimeError(f"MinerU parsing failed: {err_msg}")

                time.sleep(self.poll_interval)

            # 下载结果 ZIP
            zip_res = requests.get(full_zip_url, timeout=60)
            zip_res.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(zip_res.content)
                tmp_zip.flush()
                tmp_zip_path = tmp_zip.name

            try:
                content, markdown_content = self._process_zip_file(tmp_zip_path)
                multimodal_items = self._extract_multimodal_items(content)

                metadata = self._get_file_metadata(file_path)
                metadata.update(
                    {
                        "parser": "mineru_cloud_api",
                        "api_base_url": self.api_base_url,
                        "model_version": model_version,
                        "content_items": len(content),
                        "source_filename": os.path.basename(file_path),
                        "batch_id": batch_id,
                    }
                )

                doc_id = self._generate_doc_id(file_path, markdown_content)
                document_structure = self._build_document_structure_from_content(
                    content, metadata
                )

                return ParseResult(
                    doc_id=doc_id,
                    content=markdown_content,
                    metadata=metadata,
                    multimodal_items=multimodal_items,
                    entities=[],
                    relations=[],
                    document_structure=document_structure,
                    content_list=content,
                )
            finally:
                if os.path.exists(tmp_zip_path):
                    os.unlink(tmp_zip_path)

        except Exception as e:
            logger.error(f"MinerU Cloud API parsing failed: {e}")
            raise

    def _process_zip_file(self, zip_path: str) -> tuple[List[Dict], str]:
        """处理 ZIP 文件，提取内容"""
        import zipfile
        import json

        content_list = []
        markdown_content = ""

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                json_files = [
                    f for f in zf.namelist() if f.endswith("_content_list.json")
                ]
                for json_file in json_files:
                    try:
                        with zf.open(json_file) as f:
                            content_list = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to read {json_file}: {e}")

                md_files = [f for f in zf.namelist() if f.endswith(".md")]
                for md_file in md_files:
                    try:
                        with zf.open(md_file) as f:
                            markdown_content = f.read().decode("utf-8")
                    except Exception as e:
                        logger.warning(f"Failed to read {md_file}: {e}")

        except Exception as e:
            logger.error(f"Failed to process ZIP file: {e}")

        return content_list, markdown_content

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
                        "content": item.get("latex", ""),
                        "text": item.get("text", ""),
                        "page_idx": item.get("page_idx", 0),
                        "index": idx,
                        "metadata": item,
                    }
                )

        return multimodal_items

    def _build_document_structure_from_content(
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
                "content": item.get("text", ""),
            }
            elements.append(element)

        element_index_map = {elem["id"]: idx for idx, elem in enumerate(elements)}

        return DocumentStructure(
            elements=elements, metadata=metadata, element_index_map=element_index_map
        )
