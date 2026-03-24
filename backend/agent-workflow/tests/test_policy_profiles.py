from kardcraft.sandbox_broker.policy_profiles import (
    DEFAULT_POLICY_PROFILES,
    LimitsModel,
    PolicyProfileResolver,
)


def test_policy_profile_resolver_shell_profile_exists():
    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="unit")
    resolved = resolver.resolve("shell-tool-default")
    assert resolved.profile.payload_type == "command"
    assert resolved.profile.runtime_order[0] == "container"


def test_policy_profile_hard_cap_applies():
    resolver = PolicyProfileResolver(DEFAULT_POLICY_PROFILES, revision="unit")
    resolved = resolver.resolve(
        "shell-tool-default",
        limits_override=LimitsModel(
            timeout_seconds=9999,
            memory_mb=9999,
            cpu_seconds=9999,
            max_processes=9999,
            allow_network=False,
        ),
    )
    assert resolved.limits.timeout_seconds <= resolver.model.hard_caps.timeout_seconds_max
    assert resolved.limits.memory_mb <= resolver.model.hard_caps.memory_mb_max
    assert resolved.limits.max_processes <= resolver.model.hard_caps.max_processes_max
