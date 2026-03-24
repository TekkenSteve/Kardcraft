"""
Redis-based checkpoint saver for LangGraph.

This implements LangGraph's native BaseCheckpointSaver interface,
allowing LangGraph to automatically manage checkpoints without manual intervention.
"""
import json
import logging
import os
from typing import Optional, AsyncIterator, Dict, Any, Sequence
from datetime import datetime
from collections.abc import Iterator

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)

from ..services.redis import RedisClient

logger = logging.getLogger(__name__)


class RedisCheckpointSaver(BaseCheckpointSaver):
    """
    LangGraph native Redis checkpoint saver.
    
    This allows LangGraph to automatically manage checkpoints without
    manual save/load operations, following the framework's standard approach.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        ttl: int = 86400,  # 24 hours default
        prefix: str = "checkpoint:",
    ):
        """
        Initialize Redis checkpoint saver.

        Args:
            redis_client: Redis client instance
            ttl: Time-to-live for checkpoints in seconds
            prefix: Key prefix for Redis storage
        """
        super().__init__()
        self.redis = redis_client
        self.ttl = ttl
        self.prefix = prefix

    def _make_key(self, thread_id: str, checkpoint_id: str) -> str:
        """Create Redis key for checkpoint."""
        return f"{self.prefix}{thread_id}:{checkpoint_id}"

    def _make_thread_key(self, thread_id: str) -> str:
        """Create Redis key for thread checkpoint list."""
        return f"{self.prefix}thread:{thread_id}"

    def _extract_thread_id(self, config: RunnableConfig) -> str:
        """Extract thread_id from config."""
        return config["configurable"]["thread_id"]

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        Get checkpoint tuple (checkpoint + metadata).
        
        This is called by LangGraph to load checkpoints.
        """
        thread_id = self._extract_thread_id(config)
        checkpoint_id = config["configurable"].get("checkpoint_id")

        if checkpoint_id:
            # Load specific checkpoint
            key = self._make_key(thread_id, checkpoint_id)
            data = await self.redis.get(key)
            if data:
                try:
                    checkpoint_data = json.loads(data)
                    # Deserialize checkpoint
                    checkpoint_info = checkpoint_data["checkpoint"]
                    checkpoint_bytes = bytes.fromhex(checkpoint_info["data"])
                    checkpoint = self.serde.loads_typed((checkpoint_info["type"], checkpoint_bytes))
                    
                    metadata = CheckpointMetadata(
                        source=checkpoint_data["metadata"]["source"],
                        step=checkpoint_data["metadata"]["step"],
                        parents=checkpoint_data["metadata"]["parents"],
                    )
                    return CheckpointTuple(
                        config=config,
                        checkpoint=checkpoint,
                        metadata=metadata,
                    )
                except Exception as e:
                    logger.error(f"Failed to deserialize checkpoint {checkpoint_id}: {e}")
                    return None
        else:
            # Load latest checkpoint for thread
            thread_key = self._make_thread_key(thread_id)
            checkpoint_ids = await self.redis.lrange(thread_key, 0, 0)  # Get latest
            if checkpoint_ids:
                latest_id = checkpoint_ids[0]
                key = self._make_key(thread_id, latest_id)
                data = await self.redis.get(key)
                if data:
                    try:
                        checkpoint_data = json.loads(data)
                        # Deserialize checkpoint
                        checkpoint_info = checkpoint_data["checkpoint"]
                        checkpoint_bytes = bytes.fromhex(checkpoint_info["data"])
                        checkpoint = self.serde.loads_typed((checkpoint_info["type"], checkpoint_bytes))
                        
                        metadata = CheckpointMetadata(
                            source=checkpoint_data["metadata"]["source"],
                            step=checkpoint_data["metadata"]["step"],
                            parents=checkpoint_data["metadata"]["parents"],
                        )
                        return CheckpointTuple(
                            config=config,
                            checkpoint=checkpoint,
                            metadata=metadata,
                        )
                    except Exception as e:
                        logger.error(f"Failed to deserialize latest checkpoint: {e}")

        return None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: Dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        List checkpoints for a thread.
        
        Args:
            config: Configuration containing thread_id
            filter: Additional filtering criteria (not implemented)
            before: Return checkpoints before this configuration
            limit: Maximum number of checkpoints to return
        """
        if not config:
            return
            
        thread_id = self._extract_thread_id(config)
        thread_key = self._make_thread_key(thread_id)

        # Get checkpoint IDs (stored in reverse chronological order)
        start = 0
        if before:
            # Find position of 'before' checkpoint
            before_checkpoint_id = before["configurable"].get("checkpoint_id")
            if before_checkpoint_id:
                all_ids = await self.redis.lrange(thread_key, 0, -1)
                try:
                    start = all_ids.index(before_checkpoint_id) + 1
                except ValueError:
                    start = 0

        end = start + (limit or 10) - 1
        checkpoint_ids = await self.redis.lrange(thread_key, start, end)

        for checkpoint_id in checkpoint_ids:
            key = self._make_key(thread_id, checkpoint_id)
            data = await self.redis.get(key)
            if data:
                try:
                    checkpoint_data = json.loads(data)
                    # Deserialize checkpoint
                    checkpoint_info = checkpoint_data["checkpoint"]
                    checkpoint_bytes = bytes.fromhex(checkpoint_info["data"])
                    checkpoint = self.serde.loads_typed((checkpoint_info["type"], checkpoint_bytes))
                    
                    metadata = CheckpointMetadata(
                        source=checkpoint_data["metadata"]["source"],
                        step=checkpoint_data["metadata"]["step"],
                        parents=checkpoint_data["metadata"]["parents"],
                    )
                    yield CheckpointTuple(
                        config=config,
                        checkpoint=checkpoint,
                        metadata=metadata,
                    )
                except Exception as e:
                    logger.warning(f"Failed to deserialize checkpoint {checkpoint_id}: {e}")
                    continue

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """
        Save checkpoint.
        
        This is called automatically by LangGraph during execution.
        """
        thread_id = self._extract_thread_id(config)
        checkpoint_id = checkpoint["id"]

        try:
            # Serialize checkpoint and metadata
            checkpoint_type, checkpoint_bytes = self.serde.dumps_typed(checkpoint)
            checkpoint_data = {
                "checkpoint": {
                    "type": checkpoint_type,
                    "data": checkpoint_bytes.hex(),  # Store as hex string
                },
                "metadata": {
                    "source": metadata["source"],
                    "step": metadata["step"],
                    "parents": metadata["parents"],
                },
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "timestamp": datetime.utcnow().isoformat(),
                "worker_id": os.getenv("HOSTNAME", "unknown"),
            }

            # Store checkpoint
            key = self._make_key(thread_id, checkpoint_id)
            await self.redis.setex(key, self.ttl, json.dumps(checkpoint_data))

            # Add to thread checkpoint list (maintain order)
            thread_key = self._make_thread_key(thread_id)
            await self.redis.lpush(thread_key, checkpoint_id)
            await self.redis.expire(thread_key, self.ttl)

            # Keep only recent checkpoints (prevent unbounded growth)
            await self.redis.ltrim(thread_key, 0, 99)  # Keep latest 100

            # Add to task checkpoint set for easy lookup
            await self.redis.sadd(f"task:checkpoints:{thread_id}", checkpoint_id)
            await self.redis.expire(f"task:checkpoints:{thread_id}", self.ttl)

            logger.debug(f"Checkpoint saved: {checkpoint_id} for thread {thread_id}")

            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                }
            }

        except Exception as e:
            logger.error(f"Failed to save checkpoint {checkpoint_id}: {e}", exc_info=True)
            raise

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Store intermediate writes linked to a checkpoint.
        
        Args:
            config: Configuration of the related checkpoint
            writes: List of writes to store
            task_id: Identifier for the task creating the writes
            task_path: Path of the task creating the writes
        """
        # For now, we'll store writes as part of the checkpoint data
        # In a more sophisticated implementation, you might store them separately
        thread_id = self._extract_thread_id(config)
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        if checkpoint_id:
            writes_key = f"{self.prefix}writes:{thread_id}:{checkpoint_id}"
            serialized_writes = []
            for channel, value in writes:
                value_type, value_bytes = self.serde.dumps_typed(value)
                serialized_writes.append({
                    "channel": channel,
                    "value": {
                        "type": value_type,
                        "data": value_bytes.hex(),
                    }
                })
            
            writes_data = {
                "writes": serialized_writes,
                "task_id": task_id,
                "task_path": task_path,
                "timestamp": datetime.utcnow().isoformat(),
            }
            await self.redis.setex(writes_key, self.ttl, json.dumps(writes_data))

    async def adelete_thread(self, thread_id: str) -> None:
        """
        Clean up all checkpoints for a thread.
        
        Args:
            thread_id: Thread identifier
        """
        try:
            # Get all checkpoint IDs for thread
            thread_key = self._make_thread_key(thread_id)
            checkpoint_ids = await self.redis.lrange(thread_key, 0, -1)

            # Delete all checkpoints and their writes
            for checkpoint_id in checkpoint_ids:
                key = self._make_key(thread_id, checkpoint_id)
                writes_key = f"{self.prefix}writes:{thread_id}:{checkpoint_id}"
                await self.redis.delete(key)
                await self.redis.delete(writes_key)

            # Delete thread list and task set
            await self.redis.delete(thread_key)
            await self.redis.delete(f"task:checkpoints:{thread_id}")

            logger.info(f"Cleaned up {len(checkpoint_ids)} checkpoints for thread {thread_id}")

        except Exception as e:
            logger.error(f"Failed to cleanup thread {thread_id}: {e}", exc_info=True)

    async def cleanup_thread(self, thread_id: str):
        """
        Clean up all checkpoints for a thread.
        
        Args:
            thread_id: Thread identifier
        """
        await self.adelete_thread(thread_id)

    async def get_checkpoint_count(self, thread_id: str) -> int:
        """Get number of checkpoints for a thread."""
        try:
            thread_key = self._make_thread_key(thread_id)
            return await self.redis.llen(thread_key)
        except Exception:
            return 0

    async def health_check(self) -> bool:
        """Perform health check on Redis connection."""
        try:
            return await self.redis.verify_connection()
        except Exception:
            return False