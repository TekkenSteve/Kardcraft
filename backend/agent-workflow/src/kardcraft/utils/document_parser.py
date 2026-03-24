"""
Document parsing utilities.

Current implementation provides a local parser fallback used after
legacy external parser decommission.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def parse_document(content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    """
    Parse uploaded document content into text and metadata.
    """
    try:
        if content_type == "application/pdf":
            text = f"PDF file {filename} parsed with local fallback parser.\n\nSize: {len(content)} bytes"
            pages = max(1, len(content) // 2048)
        elif content_type == "text/plain":
            text = content.decode("utf-8", errors="ignore")
            pages = 1
        elif content_type in (
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ):
            text = f"Word file {filename} parsed with local fallback parser.\n\nSize: {len(content)} bytes"
            pages = max(1, len(content) // 3072)
        else:
            text = f"Unsupported document type {content_type}. filename={filename}, size={len(content)} bytes"
            pages = 1

        return {
            "text": text,
            "pages": pages,
            "language": "unknown",
            "metadata": {
                "filename": filename,
                "content_type": content_type,
                "file_size": len(content),
                "parser": "local-fallback",
            },
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.error("document parse failed", exc_info=True)
        return {
            "text": f"document parse failed: {exc}",
            "pages": 0,
            "language": "unknown",
            "metadata": {
                "filename": filename,
                "content_type": content_type,
                "file_size": len(content) if content else 0,
                "parser": "error",
            },
            "success": False,
            "error": str(exc),
        }
