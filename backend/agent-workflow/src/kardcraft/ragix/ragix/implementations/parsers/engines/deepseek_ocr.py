# implementations/parsers/deepseek_ocr.py - DeepSeekOCR API 解析器
"""
DeepSeekOCR API 解析器

基于 Yuxi-Know 的 deepseek_ocr_parser.py 实现
使用 SiliconFlow API 的 DeepSeek-OCR 进行文档解析
"""

import base64
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any

import requests

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class DeepSeekOCRParser(BaseFileParser):
    """DeepSeekOCR API 解析器"""

    MIME_TYPE_MAP = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = list(self.MIME_TYPE_MAP.keys())
        
        # API 配置
        self.api_key = config.params.get("api_key") or os.getenv("SILICONFLOW_API_KEY")
        if not self.api_key:
            raise ValueError("SILICONFLOW_API_KEY not set")
        
        self.api_url = "https://api.siliconflow.cn/v1/chat/completions"
        self.model = config.params.get("model", "deepseek-ai/DeepSeek-OCR")
        
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        """使用 DeepSeekOCR API 解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        try:
            logger.info(f"DeepSeekOCR starting: {file_path}")
            start_time = time.time()

            if file_ext == ".pdf":
                content = self._process_pdf(file_path)
            else:
                content = self._process_image(file_path)

            processing_time = time.time() - start_time
            logger.info(f"DeepSeekOCR finished: {file_path} - {len(content)} chars ({processing_time:.2f}s)")

            # 元数据
            metadata = self._get_file_metadata(file_path)
            metadata.update({
                "parser": "deepseek_ocr",
                "model": self.model,
            })
            
            doc_id = self._generate_doc_id(file_path, content)
            document_structure = self._build_document_structure(content, metadata)
            
            return ParseResult(
                doc_id=doc_id,
                content=content,
                metadata=metadata,
                multimodal_items=[],
                entities=[],
                relations=[],
                document_structure=document_structure
            )

        except Exception as e:
            logger.error(f"DeepSeekOCR parsing failed: {e}")
            raise

    def _process_pdf(self, pdf_path: str) -> str:
        """处理 PDF（将页面转换为图像）"""
        try:
            import fitz
            
            full_text = []
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            logger.info(f"Processing PDF with {total_pages} pages")

            for i, page in enumerate(doc):
                # 转换为图像（200 DPI）
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                
                page_text = self._call_api(img_bytes, "image/png")
                full_text.append(page_text)
                
                if (i + 1) % 10 == 0:
                    logger.info(f"Processed {i + 1}/{total_pages} pages")

            doc.close()
            return "\n\n".join(full_text)
            
        except Exception as e:
            raise RuntimeError(f"PDF processing failed: {e}")

    def _process_image(self, image_path: str) -> str:
        """处理单个图像"""
        mime_type = self._get_mime_type(image_path)
        with open(image_path, "rb") as f:
            file_content = f.read()
        return self._call_api(file_content, mime_type)

    def _call_api(self, data_bytes: bytes, mime_type: str) -> str:
        """调用 SiliconFlow API"""
        encoded_string = base64.b64encode(data_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded_string}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "<image>\n<|grounding|>Convert the document to markdown. "},
                ],
            }
        ]

        payload = {
            "model": self.model, 
            "messages": messages, 
            "max_tokens": 4096, 
            "temperature": 0.1
        }

        response = requests.post(
            self.api_url, 
            headers=self.headers, 
            json=payload, 
            timeout=120
        )

        if response.status_code != 200:
            raise RuntimeError(f"API error {response.status_code}: {response.text}")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # 清理特殊标签
        content = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "", content)
        content = re.sub(r"<\|det\|>.*?<\|/det\|>", "", content)

        return content.strip()

    def _get_mime_type(self, file_path: str) -> str:
        file_ext = Path(file_path).suffix.lower()
        return self.MIME_TYPE_MAP.get(file_ext, "image/jpeg")

    def _build_document_structure(self, text: str, metadata: Dict) -> Any:
        """构建文档结构"""
        from ...protocols.context_extractors import DocumentStructure
        
        elements = []
        
        paragraphs = text.split("\n")
        for idx, para in enumerate(paragraphs):
            if para.strip():
                element = {
                    "id": f"paragraph_{idx}",
                    "type": "text",
                    "page_idx": 0,
                    "index": idx,
                    "content": para.strip(),
                }
                elements.append(element)
        
        element_index_map = {elem["id"]: idx for idx, elem in enumerate(elements)}
        
        return DocumentStructure(
            elements=elements,
            metadata=metadata,
            element_index_map=element_index_map
        )

    def check_health(self) -> dict:
        """检查 API 可用性"""
        try:
            models_url = "https://api.siliconflow.cn/v1/models"
            response = requests.get(models_url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "DeepSeekOCR (SiliconFlow) is available",
                    "details": {"api_url": self.api_url},
                }
            elif response.status_code == 401:
                return {"status": "unhealthy", "message": "Invalid API Key"}
            else:
                return {
                    "status": "unhealthy",
                    "message": f"API Error: {response.status_code}",
                }
        except Exception as e:
            return {
                "status": "unavailable",
                "message": f"Connection failed: {str(e)}",
            }
