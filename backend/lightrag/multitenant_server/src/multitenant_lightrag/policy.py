from __future__ import annotations

from typing import Protocol

from cachetools import LRUCache


class WorkspaceEvictionPolicy(Protocol):
    def touch(self, key: str) -> None:
        ...

    def admit(self, key: str) -> str | None:
        """Admit key and optionally return a victim key to evict."""
        ...

    def remove(self, key: str) -> None:
        ...

    def clear(self) -> None:
        ...


class StrictLRUPolicy:
    """Strict global LRU policy (admit returns victim when full)."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        # value payload is irrelevant; keys carry eviction order
        self._order: LRUCache[str, None] = LRUCache(maxsize=max_size)

    def touch(self, key: str) -> None:
        if key in self._order:
            # read updates LRU order in cachetools.LRUCache
            _ = self._order[key]
            return
        self.admit(key)

    def admit(self, key: str) -> str | None:
        if key in self._order:
            self.touch(key)
            return None

        victim: str | None = None
        if len(self._order) >= self._order.maxsize:
            victim, _ = self._order.popitem()

        self._order[key] = None
        return victim

    def remove(self, key: str) -> None:
        self._order.pop(key, None)

    def clear(self) -> None:
        self._order.clear()

    def __len__(self) -> int:
        return len(self._order)
