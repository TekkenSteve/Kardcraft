"""Simplified multilingual support (Chinese + English)."""

from typing import Dict, Optional, Any


SUPPORTED_LANGUAGES = {"en", "zh"}


class LanguageDetector:
    """Simple language detector for Chinese and English."""

    def detect(self, text: str) -> str:
        """Detect if text is Chinese or English."""
        if not text:
            return "en"

        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total = len(text)

        if chinese_chars / total > 0.3:
            return "zh"
        return "en"

    def get_fallback_chain(self, lang: str) -> list[str]:
        """Get fallback chain for a language."""
        if lang in SUPPORTED_LANGUAGES:
            return [lang]
        return ["en"]


class MultilingualInstructionSet:
    """Container for bilingual instructions (zh/en)."""

    def __init__(self, instructions: Dict[str, str]):
        self.instructions = instructions

    def get(self, lang: str = "en") -> str:
        """Get instructions for language."""
        return self.instructions.get(lang, self.instructions.get("en", ""))

    def __getitem__(self, lang: str) -> str:
        return self.get(lang)


def create_bilingual_instructions(
    zh: str,
    en: str,
) -> MultilingualInstructionSet:
    """Create bilingual instructions (Chinese + English)."""
    return MultilingualInstructionSet({"zh": zh, "en": en})


_detector: Optional[LanguageDetector] = None


def get_language_detector() -> LanguageDetector:
    """Get the default language detector."""
    global _detector
    if _detector is None:
        _detector = LanguageDetector()
    return _detector
