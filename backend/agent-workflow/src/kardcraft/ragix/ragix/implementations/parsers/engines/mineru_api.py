# implementations/parsers/mineru_api.py - MinerU HTTP API 解析器
"""
MinerU HTTP API 解析器

基于 Yuxi-Know 的 mineru_parser.py 实现
使用 MinerU HTTP API 进行文档解析
"""

import os
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class MinerUAPIParser(BaseFileParser):
    """MinerU HTTP API 解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".tif",
        ]

        # 从配置或环境变量获取 API 地址
        self.server_url = config.params.get("server_url") or os.getenv(
            "MINERU_API_URI", "http://localhost:30001"
        )
        self.parse_endpoint = f"{self.server_url}/file_parse"

        # 处理参数
        self.lang_list = config.params.get("lang_list", ["ch"])
        self.backend = config.params.get("backend", "vlm-http-client")
        self.parse_method = config.params.get("parse_method", "auto")

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        """使用 MinerU HTTP API 解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        try:
            # 构建请求数据
            data = {
                "lang_list": self.lang_list,
                "backend": self.backend,
                "parse_method": self.parse_method,
                "return_md": True,
                "response_format_zip": True,
                "return_images": True,
            }

            # vlm-http-client 后端需要 server_url
            if self.backend == "vlm-http-client":
                mineru_vl_server = os.environ.get("MINERU_VL_SERVER")
                if mineru_vl_server:
                    data["server_url"] = mineru_vl_server

            logger.info(f"MinerU API starting: {file_path}")

            # 发送请求
            with open(file_path, "rb") as f:
                files = {"files": (Path(file_path).name, f, "application/octet-stream")}

                response = requests.post(
                    self.parse_endpoint,
                    files=files,
                    data=data,
                    timeout=int(os.environ.get("MINERU_TIMEOUT", 1800)),
                )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_detail = error_data.get("detail", str(error_data))
                except Exception:
                    error_detail = response.text or f"HTTP {response.status_code}"
                raise RuntimeError(f"MinerU API error: {error_detail}")

            # 处理响应（ZIP 格式）
            zip_data = response.content

            # 保存到临时文件并处理
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(zip_data)
                tmp_zip.flush()
                tmp_zip_path = tmp_zip.name

            try:
                # 解析 ZIP 文件内容
                content, markdown_content = self._process_zip_file(tmp_zip_path)

                # 提取多模态元素
                multimodal_items = self._extract_multimodal_items(content)

                # 元数据
                metadata = self._get_file_metadata(file_path)
                metadata.update(
                    {
                        "parser": "mineru_api",
                        "server_url": self.server_url,
                        "backend": self.backend,
                        "content_items": len(content),
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
                )

            finally:
                if os.path.exists(tmp_zip_path):
                    os.unlink(tmp_zip_path)

        except Exception as e:
            logger.error(f"MinerU API parsing failed: {e}")
            raise

    def _process_zip_file(self, zip_path: str) -> tuple[List[Dict], str]:
        """处理 ZIP 文件，提取内容"""
        import zipfile
        import json

        content_list = []
        markdown_content = ""

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # 查找 JSON 文件
                json_files = [
                    f for f in zf.namelist() if f.endswith("_content_list.json")
                ]

                for json_file in json_files:
                    try:
                        with zf.open(json_file) as f:
                            content_list = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to read {json_file}: {e}")

                # 查找 Markdown 文件
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
        from ...protocols.context_extractors import DocumentStructure

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

    def check_health(self) -> dict:
        """检查 MinerU 服务健康状态"""
        try:
            health_url = f"{self.server_url}/openapi.json"
            response = requests.get(health_url, timeout=5)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "MinerU 服务运行正常",
                    "details": {"server_url": self.server_url},
                }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"MinerU 服务响应异常: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "MinerU 服务无法连接",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"MinerU 健康检查失败: {str(e)}",
                "details": {"server_url": self.server_url},
            }
