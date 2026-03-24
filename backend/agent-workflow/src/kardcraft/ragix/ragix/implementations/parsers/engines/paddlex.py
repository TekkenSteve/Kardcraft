# implementations/parsers/paddlex.py - PaddleX HTTP API 解析器
"""
PaddleX HTTP API 解析器

基于 Yuxi-Know 的 paddlex_parser.py 实现
使用 PP-StructureV3 HTTP API 进行文档解析
"""

import base64
import os
import time
from pathlib import Path
from typing import List, Dict, Any

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class PaddleXParser(BaseFileParser):
    """PaddleX HTTP API 解析器"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]
        
        # 从配置或环境变量获取 API 地址
        self.server_url = config.params.get("server_url") or os.getenv("PADDLEX_URI", "http://localhost:8080")
        self.base_url = self.server_url.rstrip("/")
        self.endpoint = f"{self.base_url}/layout-parsing"
        
        # 处理参数
        self.use_table_recognition = config.params.get("use_table_recognition", True)
        self.use_formula_recognition = config.params.get("use_formula_recognition", True)
        self.use_seal_recognition = config.params.get("use_seal_recognition", False)

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        """使用 PaddleX HTTP API 解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        # 先检查服务健康状态
        health = self.check_health()
        if health["status"] != "healthy":
            raise RuntimeError(f"PaddleX service unavailable: {health['message']}")

        try:
            logger.info(f"PaddleX starting: {file_path}")
            start_time = time.time()

            # 判断文件类型
            file_type = 0 if file_ext == ".pdf" else 1

            # 编码文件
            file_content = self._encode_file_to_base64(file_path)

            # 构建请求
            payload = {
                "file": file_content,
                "fileType": file_type,
                "useTableRecognition": self.use_table_recognition,
                "useFormulaRecognition": self.use_formula_recognition,
                "useSealRecognition": self.use_seal_recognition,
            }

            response = requests.post(
                self.endpoint, 
                json=payload, 
                headers={"Content-Type": "application/json"}, 
                timeout=300
            )

            if response.status_code != 200:
                raise RuntimeError(f"PaddleX API error: {response.status_code} - {response.text}")

            api_result = response.json()

            if api_result.get("errorCode") != 0:
                raise RuntimeError(f"PaddleX API error: {api_result.get('errorMsg', 'Unknown error')}")

            # 解析结果
            result = self._parse_api_result(api_result, file_path)
            text = result.get("full_text", "")
            
            processing_time = time.time() - start_time
            logger.info(f"PaddleX finished: {file_path} - {len(text)} chars ({processing_time:.2f}s)")

            # 提取多模态元素
            multimodal_items = self._extract_multimodal_items(result)
            
            # 元数据
            metadata = self._get_file_metadata(file_path)
            metadata.update({
                "parser": "paddlex",
                "server_url": self.server_url,
                "summary": result.get("summary", {}),
            })
            
            doc_id = self._generate_doc_id(file_path, text)
            document_structure = self._build_document_structure_from_result(result, metadata)
            
            return ParseResult(
                doc_id=doc_id,
                content=text,
                metadata=metadata,
                multimodal_items=multimodal_items,
                entities=[],
                relations=[],
                document_structure=document_structure
            )

        except Exception as e:
            logger.error(f"PaddleX parsing failed: {e}")
            raise

    def _encode_file_to_base64(self, file_path: str) -> str:
        """将文件编码为 Base64"""
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _parse_api_result(self, api_result: Dict, file_path: str) -> Dict:
        """解析 API 返回结果"""
        parsed_result = {
            "success": True,
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "total_pages": 0,
            "pages": [],
            "full_text": "",
            "summary": {},
        }

        result_data = api_result.get("result", {})
        layout_results = result_data.get("layoutParsingResults", [])

        parsed_result["total_pages"] = len(layout_results)

        total_tables = 0
        total_formulas = 0
        all_text_content = []

        for page_result in layout_results:
            if "markdown" in page_result:
                markdown = page_result["markdown"]
                if markdown.get("text"):
                    all_text_content.append(markdown["text"])

            if "prunedResult" in page_result:
                pruned = page_result["prunedResult"]
                table_result = pruned.get("table_result", [])
                total_tables += len(table_result)
                formula_result = pruned.get("formula_result", [])
                total_formulas += len(formula_result)

        parsed_result["full_text"] = "\n\n".join(all_text_content)
        parsed_result["summary"] = {
            "total_tables": total_tables,
            "total_formulas": total_formulas,
            "total_characters": len(parsed_result["full_text"]),
        }

        return parsed_result

    def _extract_multimodal_items(self, result: Dict) -> List[Dict]:
        """从解析结果中提取多模态元素"""
        multimodal_items = []
        
        summary = result.get("summary", {})
        total_tables = summary.get("total_tables", 0)
        
        # 从摘要中创建表格项
        for i in range(total_tables):
            multimodal_items.append({
                "type": "table",
                "content": f"Table {i+1}",
                "table_caption": [],
                "table_footnote": [],
                "page_idx": i,
                "index": i,
                "metadata": {}
            })
        
        return multimodal_items

    def _build_document_structure_from_result(self, result: Dict, metadata: Dict):
        """从解析结果构建文档结构"""
        from ...protocols.context_extractors import DocumentStructure
        
        elements = []
        
        full_text = result.get("full_text", "")
        pages = result.get("total_pages", 0)
        
        # 按页分割
        text_parts = full_text.split("\n\n")
        for idx, text in enumerate(text_parts):
            element = {
                "id": f"element_{idx}",
                "type": "text",
                "page_idx": idx,
                "index": idx,
                "content": text,
            }
            elements.append(element)
        
        element_index_map = {elem["id"]: idx for idx, elem in enumerate(elements)}
        
        return DocumentStructure(
            elements=elements,
            metadata=metadata,
            element_index_map=element_index_map
        )

    def check_health(self) -> dict:
        """检查 PaddleX 服务健康状态"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "PaddleX 服务运行正常",
                    "details": {"server_url": self.server_url},
                }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"PaddleX 服务响应异常: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "PaddleX 服务无法连接",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"PaddleX 健康检查失败: {str(e)}",
                "details": {"server_url": self.server_url},
            }
