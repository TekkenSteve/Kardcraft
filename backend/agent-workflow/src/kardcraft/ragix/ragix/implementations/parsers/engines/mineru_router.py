"""Unified MinerU parser.

This wrapper decides whether to use:
- MinerUAPIParser (self-hosted/docker HTTP API)
- MinerUCloudAPIParser (official cloud API)
"""

import os
import tempfile
from typing import List, Optional

from ..base import BaseFileParser
from ....protocols.parsers import ParseResult
from ....utils.gotenberg_client import GotenbergConverterClient
from ....utils.util import get_ext
from .mineru_api import MinerUAPIParser
from .mineru_cloud_api import MinerUCloudAPIParser


class MinerUParser(BaseFileParser):
    """Route MinerU requests to API or Cloud parser."""

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
        self._delegate: Optional[BaseFileParser] = None

    def get_supported_extensions(self) -> List[str]:
        return self._supported_extensions

    async def parse(self, file_path: str) -> ParseResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        parse_path = file_path
        temp_pdf_path: Optional[str] = None
        file_ext = get_ext(file_path)

        if file_ext not in self._supported_extensions:
            parse_path, temp_pdf_path = self._convert_to_pdf(file_path, file_ext)

        parser = await self._get_delegate()
        try:
            return await parser.parse(parse_path)
        finally:
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                except Exception:
                    pass

    async def _get_delegate(self) -> BaseFileParser:
        if self._delegate is not None:
            return self._delegate

        backend = self._choose_backend()
        if backend == "cloud":
            parser: BaseFileParser = MinerUCloudAPIParser(self.config)
        else:
            parser = MinerUAPIParser(self.config)

        await parser.initialize()
        self._delegate = parser
        return parser

    def _choose_backend(self) -> str:
        """Choose backend using explicit config first, then env hints."""
        params = self.config.params or {}

        explicit = str(
            params.get("mineru_backend")
            or params.get("backend_route")
            or os.getenv("MINERU_BACKEND", "")
        ).strip().lower()
        if explicit in {"api", "local", "self_hosted"}:
            return "api"
        if explicit in {"cloud", "remote"}:
            return "cloud"

        # If cloud token exists, prefer cloud path.
        has_cloud_token = bool(params.get("api_token") or os.getenv("MINERU_CLOUD_API_TOKEN"))
        if has_cloud_token:
            return "cloud"

        # Default to self-hosted API (docker service).
        return "api"

    def _convert_to_pdf(self, file_path: str, file_ext: str) -> tuple[str, str]:
        converter = GotenbergConverterClient(
            base_url=self.config.params.get("gotenberg_url"),
            timeout=int(self.config.params.get("gotenberg_timeout", 120)),
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            out_pdf = tmp_pdf.name

        try:
            # Route conversion method by extension.
            if file_ext in GotenbergConverterClient.OFFICE_EXTENSIONS:
                parse_path = converter.convert_office_to_pdf(file_path, out_pdf)
            elif file_ext in {".html", ".htm"}:
                parse_path = converter.html_to_pdf(index_html=file_path, output_pdf_path=out_pdf)
            else:
                raise ValueError(
                    f"Unsupported extension for MinerU and Gotenberg conversion: {file_ext}"
                )
            return parse_path, out_pdf
        except Exception:
            if os.path.exists(out_pdf):
                try:
                    os.remove(out_pdf)
                except Exception:
                    pass
            raise
