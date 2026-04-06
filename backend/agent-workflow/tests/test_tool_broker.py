from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from kardcraft.tools.tool_broker import ToolBroker
from kardcraft.utils.file_storage_client import ConversationFileInfo, FileMetadata


class _FakeRef:
    def __init__(self, source: str) -> None:
        self._source = source

    def dict(self):
        return {"source": self._source}


class _FakeRagix:
    async def initialize(self) -> None:
        return None

    async def query(self, **kwargs):
        return SimpleNamespace(
            text=f"answer for {kwargs.get('question')}",
            citations=[_FakeRef("doc-a"), _FakeRef("doc-b")],
        )

    async def add_document(self, **kwargs):
        return f"track-{kwargs.get('file_id')}"


@pytest.mark.asyncio
async def test_tool_broker_list_history_files(monkeypatch):
    async def _fake_get_conversation_files(user_id: str, session_id: str):
        assert user_id == "u1"
        assert session_id == "s1"
        return [
            ConversationFileInfo(
                file_id="f1",
                filename="a.pdf",
                content_type="application/pdf",
                file_size=12,
                storage_key="k1",
                uploaded_at=datetime.utcnow(),
                custom_meta={},
            )
        ]

    monkeypatch.setattr(
        "kardcraft.tools.tool_broker.get_conversation_files",
        _fake_get_conversation_files,
    )

    broker = ToolBroker(ragix_factory=_FakeRagix)
    result = await broker.list_history_files(session_id="s1", user_id="u1")
    assert result["count"] == 1
    assert result["files"][0]["file_id"] == "f1"


@pytest.mark.asyncio
async def test_tool_broker_search_ragix():
    broker = ToolBroker(ragix_factory=_FakeRagix)
    result = await broker.search_ragix(
        query="hello",
        session_id="s1",
        file_ids=["f1"],
        user_id="u1",
        top_k=3,
        mode="mix",
    )
    assert "answer for hello" in result["content"]
    assert result["hit_count"] == 2
    assert result["mode"] == "mix"


@pytest.mark.asyncio
async def test_tool_broker_fetch_file_excerpt(monkeypatch):
    async def _fake_download_conversation_file(user_id: str, file_id: str):
        assert user_id == "u1"
        assert file_id == "f1"
        content = (
            "chapter 1 intro\n"
            "important keyword appears here in the middle of content\n"
            "chapter end"
        ).encode("utf-8")
        metadata = FileMetadata(
            content_type="text/plain",
            content_length=len(content),
            etag="e1",
            last_modified=datetime.utcnow(),
            custom_meta={"original_filename": "doc.txt"},
        )
        return content, metadata

    monkeypatch.setattr(
        "kardcraft.tools.tool_broker.download_conversation_file",
        _fake_download_conversation_file,
    )

    broker = ToolBroker(ragix_factory=_FakeRagix)
    result = await broker.fetch_file_excerpt(
        file_id="f1",
        user_id="u1",
        query="keyword",
        max_chars=80,
    )
    assert result["file_id"] == "f1"
    assert result["filename"] == "doc.txt"
    assert "keyword" in result["excerpt"].lower()
