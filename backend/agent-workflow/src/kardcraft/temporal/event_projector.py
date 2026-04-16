"""Entrypoint for workflow outbox -> Redis projector."""

from __future__ import annotations

import asyncio
import signal

from kardcraft.env_bootstrap import bootstrap_root_env
from kardcraft.services.workflow_event_projector import WorkflowEventProjector
from kardcraft.utils.logger import logger


async def _run() -> None:
    bootstrap_root_env(
        required_keys=(
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "REDIS_HOST",
            "REDIS_PORT",
        )
    )

    projector = WorkflowEventProjector()
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("received shutdown signal for workflow event projector")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    runner = asyncio.create_task(projector.run())
    stop_waiter = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            {runner, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if runner in done:
            # Surface projector failure so container restarts instead of silently idling.
            await runner
            return

        await projector.begin_quiesce()
        await runner
    finally:
        if not stop_waiter.done():
            stop_waiter.cancel()
            try:
                await stop_waiter
            except asyncio.CancelledError:
                pass
        await projector.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
