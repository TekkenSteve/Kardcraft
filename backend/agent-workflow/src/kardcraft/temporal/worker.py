import asyncio
import os
import signal
from temporalio.client import Client
from temporalio.worker import Worker
from kardcraft.config import Config
from kardcraft.env_bootstrap import bootstrap_root_env
from kardcraft.temporal.activities.agent_activities import AgentActivities
from kardcraft.temporal.agentos_event_activity import agentos_event_activities_from_env
from kardcraft.temporal.agentos_workflow import KardcraftAgentOSWorkflow
from kardcraft.workflow.manager import WorkflowManager
from kardcraft.services.redis import redis as redis_client
from kardcraft.utils.logger import logger


async def _shutdown_worker(worker: Worker, worker_task: asyncio.Task) -> None:
    shutdown = getattr(worker, "shutdown", None)
    if callable(shutdown):
        await shutdown()
    else:
        worker_task.cancel()


async def main():
    bootstrap_root_env(
        required_keys=(
            "TEMPORAL_ENDPOINT",
            "REDIS_HOST",
            "REDIS_PORT",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "SANDBOX_BROKER_TARGET",
            "AGENT_WORKFLOW_TASK_QUEUE",
            "TASK_ORCHESTRATOR_BASE_URL",
        )
    )

    # Load configuration
    config = Config()

    # Initialize services
    logger.info("Initializing services for Temporal Worker...")

    # Initialize Workflow Manager
    workflow_manager = WorkflowManager(
        config=config,
        redis_client=redis_client,
    )

    # Initialize Activities
    activities = AgentActivities(
        workflow_manager=workflow_manager,
        redis_client=redis_client,
    )

    # Connect to Temporal Server
    logger.info(f"Connecting to Temporal server at {config.temporal_endpoint}...")
    client = await Client.connect(config.temporal_endpoint)

    # Run Worker
    task_queue = os.environ["AGENT_WORKFLOW_TASK_QUEUE"].strip()

    registered_activities = [
        activities.execute_agent_workflow,
        activities.resume_agent_workflow,
        activities.health_check_activity,
        agentos_event_activities_from_env().emit_agentos_event,
    ]
    logger.info(
        f"Registering {len(registered_activities)} activities: {[a.fn.__name__ if hasattr(a, 'fn') else str(a) for a in registered_activities]}"
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[KardcraftAgentOSWorkflow],
        activities=registered_activities,
    )

    logger.info(f"Temporal Worker started. Listening on task queue: '{task_queue}'")

    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    worker_task = asyncio.create_task(worker.run(), name="temporal-worker-run")
    stop_wait_task = asyncio.create_task(stop_event.wait(), name="worker-stop-wait")

    try:
        done, _ = await asyncio.wait(
            {worker_task, stop_wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_event.is_set() and not worker_task.done():
            await _shutdown_worker(worker, worker_task)

        if worker_task in done:
            # Propagate worker failure if it exited unexpectedly.
            await worker_task
    except asyncio.CancelledError:
        logger.info("Worker main task cancelled")
        if not worker_task.done():
            await _shutdown_worker(worker, worker_task)
        raise
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
    finally:
        if not stop_wait_task.done():
            stop_wait_task.cancel()
            try:
                await stop_wait_task
            except asyncio.CancelledError:
                pass

        logger.info("Shutting down services...")
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
