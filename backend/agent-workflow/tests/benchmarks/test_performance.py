"""Performance benchmarks for kardcraft core paths."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from kardcraft.agent_skills.load import (
    _is_safe_path,
    _parse_skill_metadata,
    list_skills,
)
from kardcraft.sandbox_broker.policy_profiles import (
    PolicyProfileResolver,
    DEFAULT_POLICY_PROFILES,
)


class _FakeContainerRuntime:
    async def execute(self, req, limits):
        class _Result:
            success = True
            exit_code = 0
            stdout = "ok"
            stderr = ""
            duration_ms = 1
            started_at_ms = 1
            completed_at_ms = 2
            metadata = {"sandbox_runtime": "runsc", "image": "img"}

        return _Result()


class _FakeMontyRuntime:
    async def run(self, **kwargs):
        return "ok"


def _make_skills_dir(count: int) -> Path:
    root = Path(tempfile.mkdtemp())
    for i in range(count):
        d = root / f"skill-{i:04d}"
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: skill-{i:04d}\ndescription: Skill number {i}\ncategory: test\n---\n",
            encoding="utf-8",
        )
    return root


def _parse_benchmark(skills_dir: Path, n: int) -> float:
    start = time.perf_counter()
    for _ in range(n):
        for sd in skills_dir.iterdir():
            if sd.is_dir():
                md = sd / "SKILL.md"
                if md.exists():
                    _parse_skill_metadata(md, source="project")
    return time.perf_counter() - start


def _is_safe_path_benchmark(base_dir: Path, n: int) -> float:
    child = base_dir / "subdir" / "file.txt"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.touch()
    start = time.perf_counter()
    for _ in range(n):
        _is_safe_path(child, base_dir)
    return time.perf_counter() - start


def _policy_resolution_benchmark(n: int) -> float:
    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="bench")
    profiles = list(DEFAULT_POLICY_PROFILES.keys())
    start = time.perf_counter()
    for i in range(n):
        resolver.resolve(profiles[i % len(profiles)])
    return time.perf_counter() - start


@pytest.mark.benchmark(group="skill_parsing")
def test_benchmark_skill_metadata_parsing_100(benchmark):
    skills_dir = _make_skills_dir(100)
    result = benchmark(_parse_benchmark, skills_dir, 1)
    assert result > 0


@pytest.mark.benchmark(group="skill_parsing")
def test_benchmark_skill_metadata_parsing_500(benchmark):
    skills_dir = _make_skills_dir(500)
    result = benchmark(_parse_benchmark, skills_dir, 1)
    assert result > 0


@pytest.mark.benchmark(group="skill_parsing")
def test_benchmark_list_skills_100(benchmark):
    skills_dir = _make_skills_dir(100)
    result = benchmark(list_skills, project_skills_dir=skills_dir)
    assert len(result) == 100


@pytest.mark.benchmark(group="path_safety")
def test_benchmark_is_safe_path_10000_iterations(benchmark):
    base_dir = Path(tempfile.mkdtemp())
    result = benchmark(_is_safe_path_benchmark, base_dir, 10_000)
    assert result > 0


@pytest.mark.benchmark(group="policy_resolution")
def test_benchmark_policy_resolve_all_profiles_1000(benchmark):
    result = benchmark(_policy_resolution_benchmark, 1000)
    assert result > 0


@pytest.mark.benchmark(group="semaphore")
def test_benchmark_semaphore_contention(benchmark):
    sem = asyncio.Semaphore(32)

    async def acquire_all():
        tasks = [sem.acquire() for _ in range(32)]
        await asyncio.gather(*tasks)
        for _ in range(32):
            sem.release()

    result = benchmark(lambda: asyncio.run(acquire_all()))
    assert result > 0


@pytest.mark.benchmark(group="engine_routing")
@pytest.mark.asyncio
async def test_benchmark_engine_routing_100_calls(benchmark):
    from kardcraft.sandbox_broker.runtime_router import BrokerRuntimeRouter

    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="bench")
    router = BrokerRuntimeRouter(
        profile_resolver=resolver,
        monty_runtime=_FakeMontyRuntime(),
        container_runtime=_FakeContainerRuntime(),
    )

    async def run_many():
        for _ in range(100):
            await router.execute(
                workspace_id="ws",
                task_id="t1",
                user_id="u1",
                workflow_type="wf",
                tool_name="shell",
                profile_name="shell-tool-default",
                payload_type="command",
                command="echo ok",
            )

    result = benchmark(run_many)
    assert result > 0
