from __future__ import annotations

import pytest

from kardcraft.ragix.ragix.core.ragix_client import RagixClient, TrackCancelledError


class _FakeLightRAGClient:
    def __init__(self, statuses: list[str]):
        self._statuses = list(statuses)
        self._index = 0

    async def get_track_status(self, track_id: str, workspace: str | None = None):
        if self._index >= len(self._statuses):
            status = self._statuses[-1]
        else:
            status = self._statuses[self._index]
            self._index += 1
        return {"status": status}

    async def get_pipeline_status(self, workspace: str | None = None):
        return {"busy": False, "request_pending": False}


@pytest.mark.asyncio
async def test_wait_track_ready_raises_cancelled_error_for_cancelled_status():
    client = object.__new__(RagixClient)
    lightrag = _FakeLightRAGClient(["cancelled"])

    with pytest.raises(TrackCancelledError):
        await client._wait_track_ready(lightrag, "track-1", "session-1", timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_wait_track_ready_raises_runtime_error_for_failed_status():
    client = object.__new__(RagixClient)
    lightrag = _FakeLightRAGClient(["failed"])

    with pytest.raises(RuntimeError, match="track failed"):
        await client._wait_track_ready(lightrag, "track-1", "session-1", timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_wait_track_ready_returns_when_completed():
    client = object.__new__(RagixClient)
    lightrag = _FakeLightRAGClient(["completed"])

    await client._wait_track_ready(lightrag, "track-1", "session-1", timeout_seconds=0.1)
