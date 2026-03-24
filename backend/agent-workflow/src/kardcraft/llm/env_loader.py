"""LLM env bootstrap shim.

Runtime env is expected to be prepared at process entrypoint.
This module keeps a no-op shim for backward-compatible imports.
"""

from __future__ import annotations

_bootstrapped = False


def bootstrap_llm_env() -> None:
    global _bootstrapped
    _bootstrapped = True
