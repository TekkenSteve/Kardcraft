"""Policy profile schema and resolver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator


class LimitsModel(BaseModel):
    timeout_seconds: int = 60
    memory_mb: int = 512
    cpu_seconds: int = 30
    max_processes: int = 64
    allow_network: bool = False


class HardCapsModel(BaseModel):
    timeout_seconds_max: int = 600
    memory_mb_max: int = 2048
    cpu_seconds_max: int = 300
    max_processes_max: int = 512


class ContainerModel(BaseModel):
    runtime: str = "runsc"
    image: str = "kardcraft/sandbox:latest"
    read_only_rootfs: bool = True
    cap_drop_all: bool = True
    no_new_privileges: bool = True


class MontyModel(BaseModel):
    enabled: bool = False
    max_code_chars: int = 8000
    blocklist_patterns: List[str] = Field(default_factory=list)
    external_functions_allowlist: List[str] = Field(default_factory=list)


class FallbackModel(BaseModel):
    on_monty_unsupported: Literal["container"] = "container"
    on_monty_error: Literal["container"] = "container"


class ProfileModel(BaseModel):
    payload_type: Literal["command", "python"] = "python"
    runtime_order: List[Literal["monty", "container"]] = Field(
        default_factory=lambda: ["container"]
    )
    limits: LimitsModel = Field(default_factory=LimitsModel)
    monty: MontyModel = Field(default_factory=MontyModel)
    fallback: FallbackModel = Field(default_factory=FallbackModel)

    @model_validator(mode="after")
    def _validate_runtime_order(self) -> "ProfileModel":
        if not self.runtime_order:
            raise ValueError("runtime_order must include at least one runtime")
        if self.payload_type == "command" and self.runtime_order[0] == "monty":
            raise ValueError("command payload cannot use monty as first runtime")
        return self


class DefaultsModel(BaseModel):
    runtime_order: List[Literal["monty", "container"]] = Field(
        default_factory=lambda: ["container"]
    )
    limits: LimitsModel = Field(default_factory=LimitsModel)
    container: ContainerModel = Field(default_factory=ContainerModel)


class PolicyProfilesModel(BaseModel):
    version: int = 1
    defaults: DefaultsModel = Field(default_factory=DefaultsModel)
    hard_caps: HardCapsModel = Field(default_factory=HardCapsModel)
    profiles: Dict[str, ProfileModel] = Field(default_factory=dict)


DEFAULT_POLICY_PROFILES = PolicyProfilesModel(
    profiles={
        "shell-tool-default": ProfileModel(
            payload_type="command",
            runtime_order=["container"],
            limits=LimitsModel(timeout_seconds=120, allow_network=False),
            monty=MontyModel(enabled=False),
        ),
        "python-fastlane-safe": ProfileModel(
            payload_type="python",
            runtime_order=["monty", "container"],
            limits=LimitsModel(timeout_seconds=60, allow_network=False),
            monty=MontyModel(
                enabled=True,
                max_code_chars=8000,
                blocklist_patterns=[
                    r"\bimport\s+subprocess\b",
                    r"\bimport\s+socket\b",
                    r"\bos\.system\s*\(",
                ],
            ),
        ),
    }
)


@dataclass(frozen=True)
class ResolvedPolicy:
    profile_name: str
    profile: ProfileModel
    limits: LimitsModel
    container: ContainerModel
    revision: str


def _apply_hard_caps(limits: LimitsModel, caps: HardCapsModel) -> LimitsModel:
    return LimitsModel(
        timeout_seconds=min(limits.timeout_seconds, caps.timeout_seconds_max),
        memory_mb=min(limits.memory_mb, caps.memory_mb_max),
        cpu_seconds=min(limits.cpu_seconds, caps.cpu_seconds_max),
        max_processes=min(limits.max_processes, caps.max_processes_max),
        allow_network=limits.allow_network,
    )


def merge_limits(base: LimitsModel, override: Optional[LimitsModel]) -> LimitsModel:
    if override is None:
        return base
    return LimitsModel(
        timeout_seconds=override.timeout_seconds or base.timeout_seconds,
        memory_mb=override.memory_mb or base.memory_mb,
        cpu_seconds=override.cpu_seconds or base.cpu_seconds,
        max_processes=override.max_processes or base.max_processes,
        allow_network=override.allow_network,
    )


class PolicyProfileResolver:
    def __init__(self, model: PolicyProfilesModel | None = None, revision: str = "default"):
        self.model = model or DEFAULT_POLICY_PROFILES
        self.revision = revision

    def resolve(
        self,
        profile_name: str,
        limits_override: Optional[LimitsModel] = None,
    ) -> ResolvedPolicy:
        if profile_name not in self.model.profiles:
            raise KeyError(f"unknown policy profile: {profile_name}")
        profile = self.model.profiles[profile_name]
        merged = merge_limits(profile.limits, limits_override)
        capped = _apply_hard_caps(merged, self.model.hard_caps)
        return ResolvedPolicy(
            profile_name=profile_name,
            profile=profile,
            limits=capped,
            container=self.model.defaults.container,
            revision=self.revision,
        )

    @staticmethod
    def parse(data: dict, revision: str) -> "PolicyProfileResolver":
        try:
            model = PolicyProfilesModel.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"invalid policy profile schema: {exc}") from exc
        return PolicyProfileResolver(model=model, revision=revision)
