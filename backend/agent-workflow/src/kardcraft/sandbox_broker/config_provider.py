"""Control-plane config provider: etcd primary, file fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
import yaml


@dataclass(frozen=True)
class ConfigSnapshot:
    data: dict
    revision: str
    source: str


class BaseConfigProvider:
    async def load(self) -> ConfigSnapshot:
        raise NotImplementedError


class FileConfigProvider(BaseConfigProvider):
    def __init__(self, path: str):
        self.path = Path(path)

    async def load(self) -> ConfigSnapshot:
        if not self.path.exists():
            return ConfigSnapshot(data={}, revision="file:missing", source="file")
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        revision = f"file:{int(self.path.stat().st_mtime)}"
        return ConfigSnapshot(data=raw, revision=revision, source="file")


class EtcdV2ConfigProvider(BaseConfigProvider):
    def __init__(self, endpoint: str, key: str, timeout_seconds: float = 2.0):
        self.endpoint = endpoint.rstrip("/")
        self.key = key
        self.timeout_seconds = timeout_seconds

    async def load(self) -> ConfigSnapshot:
        url = f"{self.endpoint}/v2/keys/{self.key.lstrip('/')}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 404:
                    return ConfigSnapshot(data={}, revision="etcd:missing", source="etcd")
                resp.raise_for_status()
                payload = await resp.json()
                node = payload.get("node", {})
                value_raw = node.get("value", "{}")
                data = json.loads(value_raw)
                modified = node.get("modifiedIndex") or node.get("createdIndex") or 0
                revision = f"etcd:{modified}"
                return ConfigSnapshot(data=data, revision=revision, source="etcd")


class CompositeConfigProvider(BaseConfigProvider):
    def __init__(
        self,
        *,
        file_provider: FileConfigProvider,
        etcd_provider: Optional[EtcdV2ConfigProvider] = None,
    ):
        self.file_provider = file_provider
        self.etcd_provider = etcd_provider
        self._last_known_good: Optional[ConfigSnapshot] = None

    async def load(self) -> ConfigSnapshot:
        file_snapshot = await self.file_provider.load()
        if self.etcd_provider is None:
            self._last_known_good = file_snapshot
            return file_snapshot
        try:
            etcd_snapshot = await self.etcd_provider.load()
            if etcd_snapshot.data:
                self._last_known_good = etcd_snapshot
                return etcd_snapshot
            self._last_known_good = file_snapshot
            return file_snapshot
        except Exception:
            if self._last_known_good is not None:
                return self._last_known_good
            self._last_known_good = file_snapshot
            return file_snapshot
