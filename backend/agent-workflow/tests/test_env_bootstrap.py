import os

import pytest

from kardcraft.env_bootstrap import bootstrap_root_env


def _write(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_bootstrap_loads_layered_root_env_without_overriding_process_env(tmp_path, monkeypatch):
    _write(tmp_path / ".env.runtime", "CANONICAL_OK=1\nSHARED=runtime\nRUNTIME_ONLY=yes\n")
    _write(tmp_path / ".env.llm", "SHARED=llm\nLLM_ONLY=ok\n")
    _write(tmp_path / ".env.ragix", "RAGIX_ONLY=ok\n")
    monkeypatch.setenv("SHARED", "process")

    result = bootstrap_root_env(root_dir=tmp_path, required_keys=("CANONICAL_OK",), force=True)

    assert result["bootstrapped"] is True
    assert os.getenv("CANONICAL_OK") == "1"
    assert os.getenv("RUNTIME_ONLY") == "yes"
    assert os.getenv("LLM_ONLY") == "ok"
    assert os.getenv("RAGIX_ONLY") == "ok"
    assert os.getenv("SHARED") == "process"


def test_bootstrap_rejects_deprecated_alias_keys(tmp_path, monkeypatch):
    _write(tmp_path / ".env.runtime", "CANONICAL_OK=1\n")
    monkeypatch.setenv("EXECUTION_BROKER_TARGET", "legacy-target")

    with pytest.raises(RuntimeError, match="Deprecated env alias key"):
        bootstrap_root_env(root_dir=tmp_path, force=True)


def test_bootstrap_requires_canonical_keys(tmp_path, monkeypatch):
    _write(tmp_path / ".env.runtime", "SOMETHING=1\n")
    monkeypatch.delenv("MISSING_REQUIRED_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing required env keys"):
        bootstrap_root_env(root_dir=tmp_path, required_keys=("MISSING_REQUIRED_KEY",), force=True)
