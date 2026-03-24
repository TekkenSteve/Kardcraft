# implementations/parsers/rapid_ocr.py - RapidOCR 本地解析器
"""
RapidOCR 本地解析器

基于 Yuxi-Know 的 rapid_ocr_processor.py 实现
使用 RapidOCR (PP-OCRv4) 进行文字识别
"""

import os
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from kardcraft.utils.logger import logger


class RapidOCRParser(BaseFileParser):
    """RapidOCR 本地解析器 - 使用 ONNX 模型进行文字识别"""

    def __init__(self, config):
        super().__init__(config)
        self._supported_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]
        
        # OCR 模型实例
        self._ocr = None
        
        # 模型路径配置
        self.model_dir_root = config.params.get("model_dir") or os.getenv("MODEL_DIR", "/models")
        
        # 检测阈值
        self.det_box_thresh = config.params.get("det_box_thresh", 0.3)

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    def _get_model_paths(self) -> tuple:
        """获取模型文件路径"""
        model_dir = os.path.join(self.model_dir_root, "SWHL/RapidOCR")
        det_model_path = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_det_infer.onnx")
        rec_model_path = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx")
        return det_model_path, rec_model_path

    def _load_model(self):
        """延迟加载 OCR 模型"""
        if self._ocr is not None:
            return

        logger.info("Loading RapidOCR model...")

        try:
            from rapidocr_onnxruntime import RapidOCR
            
            det_model_path, rec_model_path = self._get_model_paths()
            
            # 检查模型文件是否存在
            if not os.path.exists(det_model_path) or not os.path.exists(rec_model_path):
                logger.warning(f"RapidOCR model files not found at {self.model_dir_root}, using default")
                self._ocr = RapidOCR(det_box_thresh=self.det_box_thresh)
            else:
                self._ocr = RapidOCR(
                    det_box_thresh=self.det_box_thresh, 
                    det_model_path=det_model_path, 
                    rec_model_path=rec_model_path
                )
                
            logger.info("RapidOCR model loaded successfully")
            
        except ImportError:
            raise RuntimeError("rapidocr_onnxruntime not installed. Install with: pip install rapidocr_onnxruntime")
        except Exception as e:
            raise RuntimeError(f"Failed to load RapidOCR model: {e}")

    async def parse(self, file_path: str) -> ParseResult:
        """使用 RapidOCR 解析文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if not self._supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")

        try:
            logger.info(f"RapidOCR starting: {file_path}")
            start_time = time.time()

            # 加载模型
            self._load_model()

            # 根据文件类型选择处理方法
            if file_ext == ".pdf":
                text = await self._process_pdf(file_path)
            else:
                text = self._process_image(file_path)

            processing_time = time.time() - start_time
            logger.info(f"RapidOCR finished: {file_path} - {len(text)} chars ({processing_time:.2f}s)")

            # 元数据
            metadata = self._get_file_metadata(file_path)
            metadata.update({
                "parser": "rapid_ocr",
                "model_dir": self.model_dir_root,
            })
            
            doc_id = self._generate_doc_id(file_path, text)
            document_structure = self._build_document_structure(text, metadata)
            
            return ParseResult(
                doc_id=doc_id,
                content=text,
                metadata=metadata,
                multimodal_items=[],
                entities=[],
                relations=[],
                document_structure=document_structure
            )

        except Exception as e:
            logger.error(f"RapidOCR parsing failed: {e}")
            raise

    def _process_image(self, image_path: str) -> str:
        """处理单张图像"""
        try:
            result, _ = self._ocr(image_path)
            
            if result:
                text = "\n".join([line[1] for line in result])
                return text
            else:
                logger.warning(f"RapidOCR no text detected in: {image_path}")
                return ""
                
        except Exception as e:
            raise RuntimeError(f"Image OCR processing failed: {e}")

    async def _process_pdf(self, pdf_path: str) -> str:
        """处理 PDF 文件（流式处理）"""
        try:
            import fitz
            from PIL import Image
            import numpy as np
            
            all_text = []
            pdf_doc = fitz.open(pdf_path)
            total_pages = pdf_doc.page_count

            logger.info(f"Processing PDF with {total_pages} pages")

            zoom_x = 2
            zoom_y = 2

            for page_num in range(total_pages):
                page = pdf_doc[page_num]
                
                # 转换为图像
                mat = fitz.Matrix(zoom_x, zoom_y)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # 处理图像
                text = self._process_image_from_pil(img_pil)
                all_text.append(text)

                if (page_num + 1) % 10 == 0:
                    logger.info(f"Processed {page_num + 1}/{total_pages} pages")

            pdf_doc.close()

            result_text = "\n\n".join(all_text)
            logger.info(f"PDF OCR complete: {pdf_path} - {len(result_text)} chars")
            return result_text

        except Exception as e:
            raise RuntimeError(f"PDF OCR processing failed: {e}")

    def _process_image_from_pil(self, image) -> str:
        """从 PIL 图像处理"""
        try:
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
                temp_path = tmp_file.name
                image.save(temp_path)

            try:
                result, _ = self._ocr(temp_path)
                
                if result:
                    text = "\n".join([line[1] for line in result])
                    return text
                else:
                    return ""
                    
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
        except Exception as e:
            return ""

    def _build_document_structure(self, text: str, metadata: Dict) -> Any:
        """构建文档结构"""
        from ...protocols.context_extractors import DocumentStructure
        
        elements = []
        
        # 按段落分割
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
        """检查 RapidOCR 模型是否可用"""
        try:
            det_model_path, rec_model_path = self._get_model_paths()
            model_dir = os.path.dirname(os.path.dirname(det_model_path))

            if not os.path.exists(model_dir):
                return {
                    "status": "unavailable",
                    "message": f"Model directory not found: {model_dir}",
                    "details": {"model_dir": model_dir},
                }

            if not os.path.exists(det_model_path) or not os.path.exists(rec_model_path):
                return {
                    "status": "warning",
                    "message": "Model files not found, will use default",
                    "details": {"det_model": det_model_path, "rec_model": rec_model_path},
                }

            return {
                "status": "healthy",
                "message": "RapidOCR model available",
                "details": {"model_dir": self.model_dir_root},
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Health check failed: {str(e)}",
                "details": {"error": str(e)},
            }
