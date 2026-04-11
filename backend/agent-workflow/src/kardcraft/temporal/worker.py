import asyncio
import signal
from temporalio.client import Client
from temporalio.worker import Worker
from kardcraft.config import Config
from kardcraft.env_bootstrap import bootstrap_root_env
from kardcraft.temporal.activities.agent_activities import AgentActivities
from kardcraft.workflow.manager import WorkflowManager
from kardcraft.services.redis import RedisClient
from kardcraft.utils.logger import logger


async def main():
    bootstrap_root_env(
        required_keys=(
            "TEMPORAL_ENDPOINT",
            "REDIS_HOST",
            "REDIS_PORT",
            "SANDBOX_BROKER_TARGET",
        )
    )

    # Load configuration
    config = Config()

    # Initialize services
    logger.info("Initializing services for Temporal Worker...")

    redis_client = RedisClient()

    # Initialize Workflow Manager
    workflow_manager = WorkflowManager(
        config=config,
        redis_client=redis_client,
    )
    # Note: Manager initialization might be needed if it sets up heavy resources
    # await workflow_manager.initialize()

    # Initialize Activities
    activities = AgentActivities(
        workflow_manager=workflow_manager,
        redis_client=redis_client,
    )

    # Connect to Temporal Server
    logger.info(f"Connecting to Temporal server at {config.temporal_endpoint}...")
    client = await Client.connect(config.temporal_endpoint)

    # Run Worker
    task_queue = "agent-activities-queue"

    # 列出所有注册的Activities
    registered_activities = [
        activities.execute_agent_workflow,
        activities.resume_agent_workflow,
        activities.health_check_activity,
        activities.publish_workflow_event,
    ]
    logger.info(
        f"Registering {len(registered_activities)} activities: {[a.fn.__name__ if hasattr(a, 'fn') else str(a) for a in registered_activities]}"
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        activities=registered_activities,
    )

    logger.info(f"Temporal Worker started. Listening on task queue: '{task_queue}'")
    logger.info("Starting worker.run()... This should block and poll for activities")

    # Force flush logs
    import sys

    sys.stdout.flush()
    sys.stderr.flush()

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Run until stopped
    try:
        await worker.run()
        logger.info("worker.run() returned normally")
    except asyncio.CancelledError:
        logger.info("Worker cancelled")
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
    finally:
        logger.info("Shutting down services...")
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
