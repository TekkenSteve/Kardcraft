"""Language detection and normalization utilities (LLM-first)."""

from __future__ import annotations

import json
import re
from typing import Optional

from kardcraft.llm.client import chat_complete
from kardcraft.utils.logger import logger

# Keep output language set explicit and stable for downstream prompts/cards.
_SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko", "fr", "de", "es", "ru", "pt", "it", "ar"}


def normalize_language(value: str) -> Optional[str]:
    """Normalize language names/codes into short codes."""
    if not value:
        return None

    v = value.strip().lower()
    mapping = {
        "zh": "zh",
        "zh-cn": "zh",
        "zh-hans": "zh",
        "zh-hant": "zh",
        "chinese": "zh",
        "mandarin": "zh",
        "中文": "zh",
        "汉语": "zh",
        "漢語": "zh",
        "普通话": "zh",
        "普通話": "zh",
        "简体中文": "zh",
        "繁体中文": "zh",
        "en": "en",
        "english": "en",
        "英文": "en",
        "英语": "en",
        "ja": "ja",
        "jp": "ja",
        "japanese": "ja",
        "日语": "ja",
        "日文": "ja",
        "日本語": "ja",
        "ko": "ko",
        "kr": "ko",
        "korean": "ko",
        "韩语": "ko",
        "韓語": "ko",
        "韩文": "ko",
        "韓文": "ko",
        "한국어": "ko",
        "fr": "fr",
        "french": "fr",
        "法语": "fr",
        "法文": "fr",
        "de": "de",
        "german": "de",
        "德语": "de",
        "德文": "de",
        "es": "es",
        "spanish": "es",
        "西班牙语": "es",
        "西班牙文": "es",
        "ru": "ru",
        "russian": "ru",
        "俄语": "ru",
        "俄文": "ru",
        "pt": "pt",
        "portuguese": "pt",
        "葡萄牙语": "pt",
        "葡萄牙文": "pt",
        "it": "it",
        "italian": "it",
        "意大利语": "it",
        "意大利文": "it",
        "ar": "ar",
        "arabic": "ar",
        "阿拉伯语": "ar",
        "阿拉伯文": "ar",
    }
    normalized = mapping.get(v, v)
    return normalized if normalized in _SUPPORTED_LANGUAGES else None


def _parse_json_object(text: str) -> dict:
    stripped = (text or "").strip()
    if not stripped:
        return {}

    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return {}

    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


async def detect_preferred_language_with_llm(
    user_text: str,
    *,
    default_language: str = "zh",
) -> str:
    """
    Detect preferred output language via LLM.

    Priority guidance for model:
    1) Explicit user instruction (e.g. "answer in English")
    2) Language of user's requirement/request (not pasted reference text)
    3) If ambiguous, choose the requirement language or default_language
    """
    fallback = normalize_language(default_language) or "zh"
    if not (user_text or "").strip():
        return fallback

    system_prompt = (
        "You are a language selector for response generation. "
        "Return strict JSON only: {\"language\":\"<code>\",\"reason\":\"<short>\"}. "
        "Allowed language codes: zh,en,ja,ko,fr,de,es,ru,pt,it,ar."
    )
    user_prompt = (
        "Determine the preferred output language for the assistant based on this message.\\n"
        "Rules:\\n"
        "- Explicit language request has highest priority.\\n"
        "- Distinguish copied/reference content language from user requirement language.\\n"
        "- The output should follow the language user wants assistant to use.\\n"
        f"- If ambiguous, use '{fallback}'.\\n\\n"
        f"Message:\\n{user_text}"
    )

    try:
        resp = await chat_complete(
            intent="classify",
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=120,
        )
        content = ""
        if resp and getattr(resp, "choices", None):
            message = resp.choices[0].message
            content = getattr(message, "content", "") or ""

        payload = _parse_json_object(content)
        language = normalize_language(str(payload.get("language") or ""))
        return language or fallback
    except Exception as exc:
        logger.warning("LLM language detection failed", error=str(exc))
        return fallback
