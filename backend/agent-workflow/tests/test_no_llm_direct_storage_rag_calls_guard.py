from __future__ import annotations

import re
from pathlib import Path


FORBIDDEN_IMPORT_PATTERNS = [
    re.compile(r"\bfrom\s+kardcraft\.utils\.file_storage_client\s+import\b"),
    re.compile(r"\bimport\s+kardcraft\.utils\.file_storage_client\b"),
    re.compile(r"\bfrom\s+kardcraft\.ragix\s+import\s+RagixClient\b"),
    re.compile(r"\bfrom\s+kardcraft\.ragix\.ragix\.core\.ragix_client\s+import\s+RagixClient\b"),
]

# Allowed low-level boundary module for all file-storage / ragix direct access.
ALLOWED_RELATIVE_PATHS = {
    Path("src/kardcraft/tools/tool_broker.py"),
}

# These modules are currently not exposed to the LLM tool registry path.
LEGACY_EXCLUSIONS = {
    Path("src/kardcraft/tools/file_processor.py"),
}


def _iter_target_files(repo_root: Path):
    roots = [
        repo_root / "src/kardcraft/workflow",
        repo_root / "src/kardcraft/tools",
    ]
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("*.py")


def test_no_llm_direct_storage_or_ragix_calls():
    repo_root = Path.cwd()
    violations: list[str] = []

    for file_path in _iter_target_files(repo_root):
        rel = file_path.relative_to(repo_root)
        if rel in ALLOWED_RELATIVE_PATHS or rel in LEGACY_EXCLUSIONS:
            continue

        content = file_path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_IMPORT_PATTERNS:
            if pattern.search(content):
                violations.append(f"{rel}: forbidden import pattern `{pattern.pattern}`")

    assert not violations, "Direct storage/ragix imports are forbidden for LLM-reachable code:\n" + "\n".join(violations)

