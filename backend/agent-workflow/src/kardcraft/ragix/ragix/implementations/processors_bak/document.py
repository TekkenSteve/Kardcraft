# implementations/processors/document.py - 文档处理器实现
"""
文档处理器组件实现

参考 Yuxi-Know/src/plugins/ 的设计，组合实现
"""

import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
import httpx
import requests

from ...protocols.processors_bak import DocumentProcessor, DocumentProcessorConfig, DocumentResult, HealthStatus
from ...protocols.component import BaseComponent


class MinerUProcessor(BaseComponent):
    """MinerU 文档处理器 - 参考 Yuxi-Know 的 mineru_parser.py"""
    
    def __init__(self, config: DocumentProcessorConfig):
        super().__init__(config)
        self.config: DocumentProcessorConfig = config
        
    async def _do_initialize(self) -> bool:
        """初始化处理器"""
        try:
            # 设置默认 API URL
            if not self.config.api_url:
                self.config.api_url = "http://localhost:8080/api/v1/extract"
            
            return True
        except Exception as e:
            print(f"Failed to initialize MinerU processor: {e}")
            return False
    
    async def process(self, file_path: str, params: Optional[Dict[str, Any]] = None) -> DocumentResult:
        """处理文档文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.config.max_file_size:
            raise ValueError(f"File too large: {file_size} bytes > {self.config.max_file_size} bytes")
        
        # 检查文件类型
        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")
        
        try:
            # 准备请求
            with open(file_path, 'rb') as f:
                files = {'file': (Path(file_path).name, f, 'application/octet-stream')}
                
                # 合并参数
                request_params = params or {}
                request_params.update({
                    'parse_mode': 'auto',
                    'extract_images': True,
                    'extract_tables': True,
                })
                
                # 发送请求
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.config.api_url,
                        files=files,
                        data=request_params,
                        timeout=self.config.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
            
            # 解析结果
            content = result.get('content', '')
            metadata = {
                'file_path': file_path,
                'file_size': file_size,
                'processor': 'mineru',
                'processing_time': result.get('processing_time', 0),
            }
            
            # 提取多模态项目
            multimodal_items = []
            if 'images' in result:
                for img in result['images']:
                    multimodal_items.append({
                        'type': 'image',
                        'content': img,
                        'metadata': {'source': 'mineru'}
                    })
            
            if 'tables' in result:
                for table in result['tables']:
                    multimodal_items.append({
                        'type': 'table',
                        'content': table,
                        'metadata': {'source': 'mineru'}
                    })
            
            return DocumentResult(
                content=content,
                metadata=metadata,
                multimodal_items=multimodal_items
            )
            
        except Exception as e:
            raise ValueError(f"MinerU processing failed: {e}")
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return self.config.supported_extensions or [".pdf", ".docx", ".pptx", ".xlsx"]
    
    def supports_file_type(self, file_extension: str) -> bool:
        """检查是否支持指定文件类型"""
        return file_extension.lower() in self.get_supported_extensions()
    
    async def check_health(self) -> HealthStatus:
        """检查处理器健康状态"""
        try:
            # 发送健康检查请求
            health_url = self.config.api_url.replace('/extract', '/health')
            
            async with httpx.AsyncClient() as client:
                response = await client.get(health_url, timeout=10)
                response.raise_for_status()
                
                result = response.json()
                if result.get('status') == 'ok':
                    return HealthStatus(
                        status="healthy",
                        message="MinerU service is running",
                        details=result
                    )
                else:
                    return HealthStatus(
                        status="unhealthy",
                        message="MinerU service is not healthy",
                        details=result
                    )
                    
        except Exception as e:
            return HealthStatus(
                status="unavailable",
                message=f"MinerU service is unavailable: {e}",
                details={"error": str(e)}
            )


class RapidOCRProcessor(BaseComponent):
    """RapidOCR 文档处理器 - 参考 Yuxi-Know 的 rapid_ocr_processor.py"""
    
    def __init__(self, config: DocumentProcessorConfig):
        super().__init__(config)
        self.config: DocumentProcessorConfig = config
        self.ocr_engine = None
        
    async def _do_initialize(self) -> bool:
        """初始化 OCR 引擎"""
        try:
            # 动态导入 RapidOCR
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine = RapidOCR()
            return True
        except ImportError:
            print("RapidOCR not installed. Please install it with: pip install rapidocr-onnxruntime")
            return False
        except Exception as e:
            print(f"Failed to initialize RapidOCR: {e}")
            return False
    
    async def process(self, file_path: str, params: Optional[Dict[str, Any]] = None) -> DocumentResult:
        """处理文档文件"""
        if not self.ocr_engine:
            raise RuntimeError("RapidOCR engine not initialized")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.config.max_file_size:
            raise ValueError(f"File too large: {file_size} bytes > {self.config.max_file_size} bytes")
        
        # 检查文件类型
        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise ValueError(f"Unsupported file type: {file_ext}")
        
        try:
            # 执行 OCR
            result, elapse = self.ocr_engine(file_path)
            
            # 提取文本
            content_lines = []
            if result:
                for line in result:
                    if len(line) >= 2:
                        text = line[1]
                        if text and text.strip():
                            content_lines.append(text.strip())
            
            content = '\n'.join(content_lines)
            
            metadata = {
                'file_path': file_path,
                'file_size': file_size,
                'processor': 'rapid_ocr',
                'processing_time': elapse,
                'detected_lines': len(result) if result else 0,
            }
            
            return DocumentResult(
                content=content,
                metadata=metadata,
                multimodal_items=[]  # RapidOCR 主要处理文本
            )
            
        except Exception as e:
            raise ValueError(f"RapidOCR processing failed: {e}")
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return self.config.supported_extensions or [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".pdf"]
    
    def supports_file_type(self, file_extension: str) -> bool:
        """检查是否支持指定文件类型"""
        return file_extension.lower() in self.get_supported_extensions()
    
    async def check_health(self) -> HealthStatus:
        """检查处理器健康状态"""
        try:
            if self.ocr_engine is None:
                return HealthStatus(
                    status="unavailable",
                    message="RapidOCR engine not initialized"
                )
            
            # 简单的健康检查 - 创建一个小的测试图像
            import numpy as np
            from PIL import Image
            import tempfile
            
            # 创建测试图像
            test_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
            test_img = Image.fromarray(test_img)
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                test_img.save(tmp.name)
                
                # 测试 OCR
                result, _ = self.ocr_engine(tmp.name)
                
                # 清理临时文件
                os.unlink(tmp.name)
                
                return HealthStatus(
                    status="healthy",
                    message="RapidOCR engine is working",
                    details={"test_result": "success"}
                )
                
        except Exception as e:
            return HealthStatus(
                status="error",
                message=f"RapidOCR health check failed: {e}",
                details={"error": str(e)}
            )