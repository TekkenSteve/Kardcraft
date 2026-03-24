"""Utilities for extracting JSON payloads from LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def _extract_code_fence_content(text: str) -> Optional[str]:
    """Extract content from the first ```json ... ``` block if present."""
    if not text:
        return None

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_first_json_candidate(text: str) -> Optional[str]:
    """Extract the first JSON object or array candidate from free text."""
    if not text:
        return None

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
            return text[index : index + end]
        except json.JSONDecodeError:
            continue
    return None


def safe_parse_llm_json(text: str, default: Any = None) -> Any:
    """Best-effort parse for LLM JSON output.

    Parse order:
    1. Entire response
    2. First fenced block (```json ... ```)
    3. First decodable JSON object/array in response
    """
    if default is None:
        default = {}

    if not text:
        return default

    candidates = [text.strip()]
    fenced = _extract_code_fence_content(text)
    if fenced:
        candidates.append(fenced)
    inline = _extract_first_json_candidate(text)
    if inline:
        candidates.append(inline)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    return default
