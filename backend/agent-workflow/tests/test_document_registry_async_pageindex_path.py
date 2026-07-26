from __future__ import annotations

from types import SimpleNamespace

import pytest

from kardcraft.utils import document_registry


@pytest.mark.asyncio
async def test_build_one_document_tree_uses_async_pageindex(monkeypatch):
    async def _fake_download_conversation_file(*, user_id, file_id):
        assert user_id == "user-1"
        assert file_id == "file-1"
        metadata = SimpleNamespace(custom_meta={"original_filename": "lecture.pdf"})
        return b"raw-bytes", metadata

    async_pageindex_called = {"value": False}

    async def _fake_build_document_tree_async(file_obj, *, file_id, doc_name, config):
        async_pageindex_called["value"] = True
        assert file_id == "file-1"
        assert doc_name == "lecture.pdf"
        assert hasattr(file_obj, "read")
        assert config is not None
        return {
            "file_id": file_id,
            "doc_name": doc_name,
            "title": "Lecture",
            "node_id": "0000",
            "start_index": 1,
            "end_index": 1,
            "summary": "Doc",
            "nodes": [],
        }

    monkeypatch.setattr(document_registry, "download_conversation_file", _fake_download_conversation_file)
    monkeypatch.setattr(document_registry, "build_document_tree_async", _fake_build_document_tree_async)
    monkeypatch.setattr(document_registry, "_convert_to_pdf_bytes", lambda file_bytes, metadata: b"%PDF-1.4")
    monkeypatch.setattr(document_registry, "_count_pdf_pages", lambda pdf_bytes: 1)
    monkeypatch.setattr(document_registry, "_is_low_quality_tree", lambda **kwargs: False)

    tree = await document_registry._build_one_document_tree(
        file_id="file-1",
        user_id="user-1",
        model="openai/gpt-4o-mini",
    )

    assert async_pageindex_called["value"] is True
    assert tree["file_id"] == "file-1"
    assert tree["doc_name"] == "lecture.pdf"
    assert tree["node_id"] == "0000"


@pytest.mark.asyncio
async def test_build_one_document_tree_repeated_invocations_same_loop(monkeypatch):
    async def _fake_download_conversation_file(*, user_id, file_id):
        metadata = SimpleNamespace(custom_meta={"original_filename": f"{file_id}.pdf"})
        return b"raw-bytes", metadata

    calls = {"count": 0}

    async def _fake_build_document_tree_async(file_obj, *, file_id, doc_name, config):
        calls["count"] += 1
        assert hasattr(file_obj, "read")
        assert doc_name == f"{file_id}.pdf"
        assert config is not None
        return {
            "file_id": file_id,
            "doc_name": doc_name,
            "title": "Lecture",
            "node_id": "0000",
            "start_index": 1,
            "end_index": 1,
            "summary": "Doc",
            "nodes": [],
        }

    monkeypatch.setattr(document_registry, "download_conversation_file", _fake_download_conversation_file)
    monkeypatch.setattr(document_registry, "build_document_tree_async", _fake_build_document_tree_async)
    monkeypatch.setattr(document_registry, "_convert_to_pdf_bytes", lambda file_bytes, metadata: b"%PDF-1.4")
    monkeypatch.setattr(document_registry, "_count_pdf_pages", lambda pdf_bytes: 1)
    monkeypatch.setattr(document_registry, "_is_low_quality_tree", lambda **kwargs: False)

    first = await document_registry._build_one_document_tree(
        file_id="file-a",
        user_id="user-1",
        model="openai/gpt-4o-mini",
    )
    second = await document_registry._build_one_document_tree(
        file_id="file-b",
        user_id="user-1",
        model="openai/gpt-4o-mini",
    )

    assert calls["count"] == 2
    assert first["file_id"] == "file-a"
    assert second["file_id"] == "file-b"


def test_no_context_pageindex_tree_is_low_quality_even_for_single_page():
    tree = {
        "doc_name": "lecture.pdf",
        "title": "Summary Overview",
        "summary": "Document title: Summary Overview",
        "nodes": [
            {
                "title": "Summary Overview",
                "node_id": "0001",
                "start_index": 1,
                "end_index": 1,
                "summary": "Sorry, I'm not able to provide an answer.[no-context]",
            }
        ],
    }

    assert document_registry._is_low_quality_tree(
        tree=tree,
        file_id="file-1",
        pdf_page_count=1,
    ) is True
