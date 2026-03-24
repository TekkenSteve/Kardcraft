from __future__ import annotations

import copy
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CollectionHandle:
    col: Any
    path: str
    tmpdir: str


class CollectionPool:
    """Lightweight pool for reusable headless Anki collections."""

    def __init__(self, collection_cls: Any, max_size: int = 4) -> None:
        self._collection_cls = collection_cls
        self._max_size = max(1, int(max_size))
        self._lock = threading.Lock()
        self._pool: list[CollectionHandle] = []
        self._created_count = 0
        self._borrowed_count = 0

    def _new_handle(self) -> CollectionHandle:
        tmpdir = tempfile.mkdtemp(prefix="kardcraft_anki_pool_")
        path = str(Path(tmpdir) / "runtime.anki2")
        col = self._collection_cls(path)
        self._created_count += 1
        return CollectionHandle(col=col, path=path, tmpdir=tmpdir)

    def acquire(self) -> CollectionHandle:
        with self._lock:
            if self._pool:
                handle = self._pool.pop()
                self._borrowed_count += 1
                return handle
        handle = self._new_handle()
        with self._lock:
            self._borrowed_count += 1
        return handle

    @staticmethod
    def _cleanup_files(path: str, tmpdir: str) -> None:
        for suffix in ("", "-wal", "-shm"):
            target = path + suffix
            if os.path.exists(target):
                os.remove(target)
        if os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _reset_handle(self, handle: CollectionHandle) -> CollectionHandle:
        try:
            handle.col.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            target = handle.path + suffix
            if os.path.exists(target):
                os.remove(target)
        handle.col = self._collection_cls(handle.path)
        return handle

    def release(self, handle: CollectionHandle) -> None:
        try:
            handle = self._reset_handle(handle)
        except Exception:
            self._cleanup_files(handle.path, handle.tmpdir)
            return

        with self._lock:
            if len(self._pool) < self._max_size:
                self._pool.append(handle)
                return
        try:
            handle.col.close()
        except Exception:
            pass
        self._cleanup_files(handle.path, handle.tmpdir)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._pool),
                "max_size": self._max_size,
                "created": self._created_count,
                "borrowed": self._borrowed_count,
            }

    def shutdown(self) -> None:
        with self._lock:
            handles = list(self._pool)
            self._pool.clear()
        for handle in handles:
            try:
                handle.col.close()
            except Exception:
                pass
            self._cleanup_files(handle.path, handle.tmpdir)


class PreviewLRUCache:
    def __init__(self, max_size: int = 256) -> None:
        from collections import OrderedDict

        self._max_size = max(1, int(max_size))
        self._lock = threading.Lock()
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return copy.deepcopy(item)

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = copy.deepcopy(value)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._store),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
            }
