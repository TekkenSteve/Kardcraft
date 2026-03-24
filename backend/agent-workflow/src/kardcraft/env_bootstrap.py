"""Entrypoint-only environment bootstrap for root layered env files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dotenv import dotenv_values

_BOOTSTRAPPED = False

DEPRECATED_ALIAS_KEYS = {
    "EXECUTION_BROKER_TARGET": "SANDBOX_BROKER_TARGET",
    "TEMPORAL_HOST": "TEMPORAL_ENDPOINT",
}


def _resolve_root_dir(root_dir: str | Path | None) -> Path:
    if root_dir is not None:
        return Path(root_dir).expanduser().resolve()

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "docker-compose.yml").exists() and (candidate / "backend").exists():
            return candidate
    return current


def _load_layer(path: Path) -> int:
    if not path.exists():
        return 0
    injected = 0
    for key, value in dotenv_values(path).items():
        if key and value is not None and key not in os.environ:
            os.environ[str(key)] = str(value)
            injected += 1
    return injected


def bootstrap_root_env(
    *,
    root_dir: str | Path | None = None,
    required_keys: Iterable[str] = (),
    force: bool = False,
) -> dict[str, object]:
    """Load root layered env files once and validate canonical runtime keys."""

    global _BOOTSTRAPPED
    if _BOOTSTRAPPED and not force:
        return {"bootstrapped": True, "loaded_files": [], "injected": 0}

    repo_root = _resolve_root_dir(root_dir)
    layer_paths = [
        repo_root / ".env.runtime",
        repo_root / ".env.llm",
        repo_root / ".env.ragix",
    ]

    loaded_files: list[str] = []
    injected = 0
    for path in layer_paths:
        count = _load_layer(path)
        if path.exists():
            loaded_files.append(str(path))
            injected += count

    alias_hits = [key for key in DEPRECATED_ALIAS_KEYS if os.getenv(key) is not None]
    if alias_hits:
        mappings = ", ".join(f"{key}->{DEPRECATED_ALIAS_KEYS[key]}" for key in alias_hits)
        raise RuntimeError(
            f"Deprecated env alias key(s) detected: {mappings}. "
            "Use canonical key names only."
        )

    missing_required = [key for key in required_keys if not os.getenv(key)]
    if missing_required:
        raise RuntimeError(
            "Missing required env keys: " + ", ".join(sorted(missing_required))
        )

    _BOOTSTRAPPED = True
    return {
        "bootstrapped": True,
        "loaded_files": loaded_files,
        "injected": injected,
        "root_dir": str(repo_root),
    }
