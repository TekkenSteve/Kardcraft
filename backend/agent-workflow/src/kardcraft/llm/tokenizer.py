"""Tokenizer utilities for model-aware token counting."""

from __future__ import annotations

from typing import Any

from litellm import token_counter as _litellm_token_counter


def token_counter(*args: Any, **kwargs: Any) -> int:
    return _litellm_token_counter(*args, **kwargs)

