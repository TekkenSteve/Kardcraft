"""
Gotenberg client wrapper (SDK-based).

Design goals:
- Keep all Gotenberg SDK calls in one place.
- Provide stable utility methods for business code.
- Handle both SingleFileResponse and ZipFileResponse consistently.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import requests
from gotenberg_client import GotenbergClient


class GotenbergConversionError(RuntimeError):
    pass


@dataclass
class GotenbergPreparedInput:
    original_path: str
    parse_path: str
    parse_ext: str
    converted: bool
    source_ext: str
    temp_pdf_path: Optional[str] = None

    def cleanup(self) -> None:
        if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
            try:
                os.remove(self.temp_pdf_path)
            except Exception:
                pass

    def annotate_metadata(self, metadata: Dict[str, object]) -> None:
        if not self.converted:
            return
        metadata["source_file"] = Path(self.original_path).name
        metadata["converted_from"] = self.source_ext
        metadata["converted_by"] = "gotenberg"


class GotenbergConverterClient:
    """Wrapper around stumpylog/gotenberg-client."""

    OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".ods", ".odp"}

    def __init__(self, base_url: Optional[str] = None, timeout: int = 120):
        self.base_url = (base_url or os.getenv("GOTENBERG_URL", "http://gotenberg:3000")).rstrip("/")
        self.timeout = timeout

    # ---------- basic ----------
    def health(self) -> Dict[str, object]:
        url = f"{self.base_url}/health"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def can_convert(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in self.OFFICE_EXTENSIONS

    def should_convert(self, file_path: str, enabled: bool = True) -> bool:
        return enabled and self.can_convert(file_path) and Path(file_path).suffix.lower() != ".pdf"

    # ---------- response handling ----------
    @staticmethod
    def _persist_response(
        response: object,
        output_path: Path,
        zip_extract_dir: Optional[Path] = None,
    ) -> str:
        # SDK contract:
        # - SingleFileResponse has to_file()
        # - ZipFileResponse has to_file() and extract_to()
        if zip_extract_dir is not None and hasattr(response, "extract_to"):
            zip_extract_dir.mkdir(parents=True, exist_ok=True)
            response.extract_to(zip_extract_dir)
            return str(zip_extract_dir)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not hasattr(response, "to_file"):
            raise GotenbergConversionError("Unexpected Gotenberg response type (missing to_file)")
        response.to_file(output_path)
        return str(output_path)

    # ---------- chromium routes ----------
    def html_to_pdf(
        self,
        index_html: str,
        output_pdf_path: str,
        resources: Optional[Sequence[str]] = None,
    ) -> str:
        index_path = Path(index_html)
        with GotenbergClient(self.base_url) as client:
            with client.chromium.html_to_pdf() as route:
                route = route.index(index_path)
                for resource in resources or []:
                    route = route.resource(Path(resource))
                response = route.run()
                return self._persist_response(response, Path(output_pdf_path))

    def url_to_pdf(
        self,
        url: str,
        output_pdf_path: str,
        landscape: bool = False,
    ) -> str:
        with GotenbergClient(self.base_url) as client:
            with client.chromium.url_to_pdf() as route:
                route = route.url(url)
                if landscape:
                    # Keep it simple to avoid hard dependency on option enums.
                    route = route.orient("landscape")
                response = route.run()
                return self._persist_response(response, Path(output_pdf_path))

    # ---------- libreoffice routes ----------
    def convert_office_to_pdf(
        self,
        input_path: str,
        output_pdf_path: str,
    ) -> str:
        src = Path(input_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {input_path}")
        if not self.can_convert(input_path):
            raise GotenbergConversionError(
                f"Unsupported extension for Office conversion: {src.suffix}"
            )

        try:
            with GotenbergClient(self.base_url) as client:
                with client.libre_office.to_pdf() as route:
                    response = route.convert(src).run()
                    return self._persist_response(response, Path(output_pdf_path))
        except Exception as e:
            raise GotenbergConversionError(f"Gotenberg Office conversion failed: {e}") from e

    def convert_multiple_office_to_pdf(
        self,
        input_paths: Iterable[str],
        output_path: str,
        merge: bool = False,
        zip_extract_dir: Optional[str] = None,
    ) -> str:
        files = [Path(p) for p in input_paths]
        for p in files:
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            if not self.can_convert(str(p)):
                raise GotenbergConversionError(
                    f"Unsupported extension for Office conversion: {p.suffix}"
                )

        with GotenbergClient(self.base_url) as client:
            with client.libre_office.to_pdf() as route:
                for p in files:
                    route = route.convert(p)
                if merge:
                    route = route.merge()
                response = route.run()
                extract_dir = Path(zip_extract_dir) if zip_extract_dir else None
                return self._persist_response(response, Path(output_path), zip_extract_dir=extract_dir)

    # ---------- pdf routes ----------
    def merge_pdfs(self, pdf_paths: Sequence[str], output_pdf_path: str) -> str:
        files = [Path(p) for p in pdf_paths]
        for p in files:
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            if p.suffix.lower() != ".pdf":
                raise GotenbergConversionError(f"merge_pdfs only accepts PDF files: {p}")

        with GotenbergClient(self.base_url) as client:
            response = client.merge(files).run()
            return self._persist_response(response, Path(output_pdf_path))

    # ---------- smart parser hook ----------
    def prepare_for_parse(
        self,
        file_path: str,
        enabled: bool = True,
    ) -> GotenbergPreparedInput:
        ext = Path(file_path).suffix.lower()
        if not self.should_convert(file_path, enabled=enabled):
            return GotenbergPreparedInput(
                original_path=file_path,
                parse_path=file_path,
                parse_ext=ext,
                converted=False,
                source_ext=ext,
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            temp_pdf = tmp_pdf.name
        parse_path = self.convert_office_to_pdf(file_path, temp_pdf)
        return GotenbergPreparedInput(
            original_path=file_path,
            parse_path=parse_path,
            parse_ext=".pdf",
            converted=True,
            source_ext=ext,
            temp_pdf_path=temp_pdf,
        )

