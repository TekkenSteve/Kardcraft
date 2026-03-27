"""
Simple parser router.

Route by:
1) extension group
2) file size
3) optional complexity hint
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Type

from ..parsers.base import BaseFileParser
from ..parsers.engines.mineru_router import MinerUParser
from ..parsers.engines.deepseek_ocr import DeepSeekOCRParser
# from ..parsers.engines.enhanced_markdown import EnhancedMarkdownParser
from ..parsers.engines.docling import DoclingParser
from ...utils.util import get_ext

class FileTypeGroup(Enum):
    TEXT = auto()
    PDF = auto()
    OFFICE = auto()
    IMAGE = auto()
    AUDIO = auto()
    EMAIL = auto()
    OTHER = auto()


@dataclass(frozen=True)
class FileInfo:
    group: FileTypeGroup
    file_ext: str


@dataclass(frozen=True)
class ParserSelection:
    group: FileTypeGroup
    parser_cls: Optional[Type[BaseFileParser]]


class ParserRouter:
    """Suffix-first router with light heuristic rules."""

    TEXT_EXTS = {".txt", ".md", ".markdown", ".csv"}
    PDF_EXTS = {".pdf"}
    OFFICE_EXTS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    AUDIO_EXTS = {".wav", ".mp3", ".aac", ".flac", ".ogg"}
    EMAIL_EXTS = {".msg", ".eml"}

    # Small file threshold for lightweight parser path.
    # SMALL_FILE_BYTES = 500 * 1024

    

    def get_file_type_group(self, file_path: str) -> FileInfo:
        file_ext = get_ext(file_path)
        if file_ext in self.TEXT_EXTS:
            group = FileTypeGroup.TEXT
        elif file_ext in self.PDF_EXTS:
            group = FileTypeGroup.PDF
        elif file_ext in self.OFFICE_EXTS:
            group = FileTypeGroup.OFFICE
        elif file_ext in self.IMAGE_EXTS:
            group = FileTypeGroup.IMAGE
        elif file_ext in self.AUDIO_EXTS:
            group = FileTypeGroup.AUDIO
        elif file_ext in self.EMAIL_EXTS:
            group = FileTypeGroup.EMAIL
        else:
            group = FileTypeGroup.OTHER
        return FileInfo(group=group, file_ext=file_ext)

    def select_parser(
        self,
        file_path: str,
    ) -> ParserSelection:
        file = self.get_file_type_group(file_path)
        # file_size = Path(file_path).stat().st_size # Size-based routing can be added here if needed.
        if file.group == FileTypeGroup.TEXT:
            # if file.file_ext in {".md"}:
            #     return ParserSelection(file.group, EnhancedMarkdownParser)
            return ParserSelection(file.group, MinerUParser)
        elif file.group == FileTypeGroup.PDF:
            return ParserSelection(file.group, MinerUParser)
        elif file.group == FileTypeGroup.OFFICE:
            return ParserSelection(file.group, DoclingParser)
        elif file.group == FileTypeGroup.IMAGE:
            return ParserSelection(file.group, DeepSeekOCRParser)
        elif file.group == FileTypeGroup.AUDIO:
            raise ValueError("Audio files are not supported for parsing yet.")
        elif file.group == FileTypeGroup.EMAIL:
            raise ValueError("Email files are not supported for parsing yet.")
        else:
            raise ValueError("Unknown file type.")
