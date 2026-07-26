from __future__ import annotations

from io import BytesIO

import pytest

from kardcraft.pageindex import page_index
from kardcraft.utils.logger import logger as app_logger

from kardcraft.pageindex import api
from kardcraft.pageindex.contracts import PageIndexBuildConfig


@pytest.mark.asyncio
async def test_build_document_tree_async_normalizes_payload(monkeypatch):
    async def _fake_page_index_main_async(_file_obj, _opt, doc_name=None):
        assert doc_name == "demo.pdf"
        return {
            "doc_name": "demo.pdf",
            "doc_description": "short summary",
            "structure": [
                {
                    "title": "Section A",
                    "node_id": "0001",
                    "start_index": 1,
                    "end_index": 2,
                    "summary": "A summary",
                }
            ],
        }

    monkeypatch.setattr(api, "page_index_main_async", _fake_page_index_main_async)

    tree = await api.build_document_tree_async(
        BytesIO(b"%PDF-1.4\n%fake\n"),
        file_id="file-1",
        doc_name="demo.pdf",
        config=PageIndexBuildConfig(model="openai/gpt-4o-mini"),
    )

    assert tree["file_id"] == "file-1"
    assert tree["doc_name"] == "demo.pdf"
    assert tree["title"] == "demo.pdf"
    assert tree["node_id"] == "0000"
    assert tree["start_index"] == 1
    assert tree["end_index"] == 2
    assert tree["summary"] == "short summary"
    assert len(tree["nodes"]) == 1
    assert tree["nodes"][0]["node_id"] == "0001"


def test_pageindex_legacy_logger_name_uses_bound_logger() -> None:
    assert page_index.logger is app_logger
