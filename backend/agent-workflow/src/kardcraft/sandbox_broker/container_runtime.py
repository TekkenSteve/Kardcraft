"""Container runtime for sandbox broker (no dependency on legacy execution_* modules)."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class ContainerLimits:
    timeout_seconds: int
    memory_mb: int
    cpu_seconds: int
    max_processes: int
    allow_network: bool = False


@dataclass(frozen=True)
class ContainerRequest:
    workspace_id: str
    task_id: str
    language: str = "python"
    command: Optional[str] = None
    code: Optional[str] = None
    env: Dict[str, str] = None


@dataclass(frozen=True)
class ContainerResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    started_at_ms: int
    completed_at_ms: int
    metadata: Dict[str, str]


class ContainerRuntime:
    def __init__(
        self,
        *,
        image: str = "kardcraft/sandbox:latest",
        runtime: str = "runsc",
        workdir: str = "/workspace",
        seccomp_profile: str = "/etc/docker/seccomp.json",
        apparmor_profile: str = "docker-default",
        runner: Runner = subprocess.run,
    ):
        self.image = image
        self.runtime = runtime
        self.workdir = workdir
        self.seccomp_profile = seccomp_profile
        self.apparmor_profile = apparmor_profile
        self.runner = runner

    async def execute(self, request: ContainerRequest, limits: ContainerLimits) -> ContainerResult:
        started = int(time.time() * 1000)
        command, workspace_temp = self._build_docker_command(request, limits)
        try:
            proc = await asyncio.to_thread(
                self.runner,
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=limits.timeout_seconds + 5,
            )
        except subprocess.TimeoutExpired:
            completed = int(time.time() * 1000)
            return ContainerResult(
                success=False,
                exit_code=124,
                stdout="",
                stderr=f"container execution timed out after {limits.timeout_seconds} seconds",
                duration_ms=max(0, completed - started),
                started_at_ms=started,
                completed_at_ms=completed,
                metadata={
                    "image": self.image,
                    "sandbox_runtime": self.runtime,
                    "seccomp_profile": self.seccomp_profile,
                    "apparmor_profile": self.apparmor_profile,
                    "docker_command": " ".join(shlex.quote(part) for part in command),
                },
            )
        finally:
            shutil.rmtree(workspace_temp, ignore_errors=True)
        completed = int(time.time() * 1000)
        return ContainerResult(
            success=(proc.returncode == 0),
            exit_code=int(proc.returncode),
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            duration_ms=max(0, completed - started),
            started_at_ms=started,
            completed_at_ms=completed,
            metadata={
                "image": self.image,
                "sandbox_runtime": self.runtime,
                "seccomp_profile": self.seccomp_profile,
                "apparmor_profile": self.apparmor_profile,
                "docker_command": " ".join(shlex.quote(part) for part in command),
            },
        )

    def _build_docker_command(self, request: ContainerRequest, limits: ContainerLimits) -> tuple[List[str], str]:
        workspace_temp = tempfile.mkdtemp(prefix=f"sandbox-{request.workspace_id}-")
        command = self._resolve_command(request)
        docker_cmd: List[str] = [
            "docker",
            "run",
            "--rm",
            f"--runtime={self.runtime}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--security-opt",
            f"seccomp={self.seccomp_profile}",
            "--security-opt",
            f"apparmor={self.apparmor_profile}",
            "--pids-limit",
            str(limits.max_processes),
            "--memory",
            f"{limits.memory_mb}m",
            "--cpus",
            str(max(0.1, limits.cpu_seconds / max(limits.timeout_seconds, 1))),
            "--user",
            "1000:1000",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--tmpfs",
            f"{self.workdir}:rw,nosuid,nodev,size=128m",
            "--workdir",
            self.workdir,
            "-e",
            f"WORKSPACE_ID={request.workspace_id}",
            "-e",
            f"TASK_ID={request.task_id}",
            "-v",
            f"{workspace_temp}:{self.workdir}",
        ]
        if limits.allow_network:
            docker_cmd.extend(["--network", "bridge"])
        else:
            docker_cmd.extend(["--network", "none"])
        for key, value in (request.env or {}).items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        docker_cmd.append(self.image)
        docker_cmd.extend(["sh", "-lc", command])
        return docker_cmd, workspace_temp

    def _resolve_command(self, request: ContainerRequest) -> str:
        if request.command and request.command.strip():
            return request.command.strip()
        code = (request.code or "").strip()
        random_suffix = uuid.uuid4().hex[:12]
        script_path = Path(f"/tmp/exec-{os.getpid()}-{random_suffix}.py")
        return f"cat > {script_path} << 'PY'\n{code}\nPY\npython {script_path}\nrm -f {script_path}"

    def check_runtime_ready(self) -> tuple[bool, str]:
        return check_sandbox_runtime_ready(self.runner, self.runtime)


def check_sandbox_runtime_ready(
    runner: Runner = subprocess.run, runtime_name: str = "runsc"
) -> tuple[bool, str]:
    try:
        proc = runner(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode != 0:
            return False, f"docker-info-failed:{proc.stderr.strip()}"
        output = proc.stdout or ""
        if runtime_name not in output:
            return False, f"runtime-missing:{runtime_name}"
        return True, "ready"
    except Exception as exc:
        return False, f"runtime-check-error:{exc}"
