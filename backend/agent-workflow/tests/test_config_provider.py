import json

from kardcraft.sandbox_broker.config_provider import (
    CompositeConfigProvider,
    ConfigSnapshot,
    FileConfigProvider,
)


class _FailingEtcdProvider:
    async def load(self):
        raise RuntimeError("etcd down")


class _StaticEtcdProvider:
    async def load(self):
        return ConfigSnapshot(
            data={"version": 1, "profiles": {"x": {"payload_type": "python", "runtime_order": ["container"]}}},
            revision="etcd:1",
            source="etcd",
        )


async def test_composite_provider_prefers_etcd_when_available(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    provider = CompositeConfigProvider(
        file_provider=FileConfigProvider(str(path)),
        etcd_provider=_StaticEtcdProvider(),
    )
    snap = await provider.load()
    assert snap.source == "etcd"
    assert snap.revision.startswith("etcd:")


async def test_composite_provider_falls_back_to_file_when_etcd_fails(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("version: 1\nprofiles: {}\n", encoding="utf-8")
    provider = CompositeConfigProvider(
        file_provider=FileConfigProvider(str(path)),
        etcd_provider=_FailingEtcdProvider(),
    )
    snap = await provider.load()
    assert snap.source == "file"
    assert snap.revision.startswith("file:")
