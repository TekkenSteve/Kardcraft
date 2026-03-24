"""Sandbox broker gRPC server entrypoint."""

from __future__ import annotations

import asyncio

import grpc

from kardcraft.config import Config
from kardcraft.env_bootstrap import bootstrap_root_env
from kardcraft.sandbox_broker.config_provider import (
    CompositeConfigProvider,
    EtcdV2ConfigProvider,
    FileConfigProvider,
)
from kardcraft.sandbox_broker.service import SandboxBrokerService
from kardcraft.sandbox_broker_pb2_grpc import add_SandboxBrokerServiceServicer_to_server
from kardcraft.utils.logger import logger


async def serve() -> None:
    bootstrap_root_env(
        required_keys=(
            "SANDBOX_BROKER_ADDR",
            "SANDBOX_BROKER_TARGET",
            "SANDBOX_BROKER_POLICY_FILE",
        )
    )
    config = Config()

    file_provider = FileConfigProvider(config.sandbox_broker_policy_file)
    etcd_provider = (
        EtcdV2ConfigProvider(
            config.sandbox_broker_etcd_endpoint,
            config.sandbox_broker_etcd_policy_key,
        )
        if config.sandbox_broker_etcd_enabled
        else None
    )
    provider = CompositeConfigProvider(
        file_provider=file_provider,
        etcd_provider=etcd_provider,
    )

    server = grpc.aio.server()
    add_SandboxBrokerServiceServicer_to_server(
        SandboxBrokerService(
            provider,
            max_concurrent_executions=config.sandbox_broker_max_concurrent_executions,
            queue_wait_seconds=config.sandbox_broker_queue_wait_seconds,
            policy_refresh_ttl_seconds=config.sandbox_broker_policy_refresh_ttl_seconds,
        ),
        server,
    )
    server.add_insecure_port(config.sandbox_broker_addr)
    await server.start()
    logger.info("Sandbox broker started", addr=config.sandbox_broker_addr)
    await server.wait_for_termination()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
