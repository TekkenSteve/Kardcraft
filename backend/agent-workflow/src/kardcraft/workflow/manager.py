"""
Enhanced workflow manager with native LangGraph integration.

This manager provides a flattened architecture that directly integrates
with LangGraph using Redis for checkpoint persistence.
"""

import asyncio
import uuid
import time
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass

from .redis_checkpoint_saver import RedisCheckpointSaver
from .exceptions import (
    WorkflowExecutionError,
    WorkflowNotFoundError,
    WorkflowTimeoutError,
)
from .graphs.main_graph.builder import build_main_graph
from .graphs.main_graph.state import Context as MainGraphContext
from .graphs.card_template_graph.builder import build_card_template_graph

# from .graphs.research_graph.builder import build_research_graph
from ..services.redis import RedisClient
from ..config import Config
from ..utils.logger import logger


@dataclass
class WorkflowResult:
    """Simple workflow execution result wrapper."""

    result: Dict[str, Any]
    checkpoint_id: Optional[str] = None
    execution_time_ms: float = 0.0


from enum import Enum


class WorkflowStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowManager:
    """
    Workflow manager for LangGraph.

    Responsibilities:
    1. Build LangGraph instances with correct workspace context
    2. Execute graphs with checkpointing
    3. Stream events to callback (for SSE)
    """

    def __init__(
        self,
        config: Config,
        redis_client: RedisClient,
    ):
        self.config = config
        self.redis = redis_client

        # Initialize Redis checkpoint saver
        self.checkpoint_saver = RedisCheckpointSaver(
            redis_client=redis_client,
            ttl=86400 * 7,  # 7 days retention
            prefix="checkpoint:",
        )

    def _get_graph(self, workflow_type: str):
        """Get or create graph for workflow type."""
        if workflow_type == "main":
            return build_main_graph().with_config(
                checkpointer=self.checkpoint_saver
            )
        elif workflow_type == "card_template":
            return build_card_template_graph().with_config(
                checkpointer=self.checkpoint_saver
            )
        # elif workflow_type == "card_editing":
        #     return build_card_editing_graph().with_config(
        #         checkpointer=self.checkpoint_saver
        #     )
        else:
            raise WorkflowExecutionError(f"Unknown workflow type: {workflow_type}")

    def _summarize_scalar(self, value: Any, max_text_len: int = 280) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            compact = value.strip()
            if len(compact) <= max_text_len:
                return compact
            return compact[:max_text_len] + "...[truncated]"
        return None

    def _summarize_node_output(self, node_name: str, node_output: Any) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"node_name": node_name}
        if isinstance(node_output, dict):
            keys = list(node_output.keys())
            summary["keys"] = keys[:20]
            if len(keys) > 20:
                summary["keys_truncated"] = len(keys) - 20

            scalar_fields = [
                "message",
                "status_message",
                "progress_message",
                "error",
                "reason",
                "intent_type",
                "stage",
                "phase",
            ]
            for field in scalar_fields:
                if field in node_output:
                    v = self._summarize_scalar(node_output.get(field))
                    if v is not None:
                        summary[field] = v

            for field in ["final_cards", "approved_cards", "candidate_cards", "selected_cards", "knowledge_nodes", "saved_card_ids"]:
                if field in node_output and isinstance(node_output.get(field), list):
                    summary[f"{field}_count"] = len(node_output.get(field) or [])

            for k, v in node_output.items():
                if isinstance(v, list):
                    summary[f"{k}_count"] = len(v)
                elif isinstance(v, dict):
                    summary[f"{k}_keys"] = list(v.keys())[:10]

            summary["payload_type"] = "dict"
            summary["payload_size"] = len(str(node_output))
            return summary

        if isinstance(node_output, list):
            summary["payload_type"] = "list"
            summary["payload_size"] = len(str(node_output))
            summary["items_count"] = len(node_output)
            sample: List[Any] = []
            for item in node_output[:5]:
                val = self._summarize_scalar(item)
                sample.append(val if val is not None else str(type(item)))
            summary["sample"] = sample
            return summary

        scalar = self._summarize_scalar(node_output)
        if scalar is not None:
            summary["payload_type"] = "scalar"
            summary["value"] = scalar
            summary["payload_size"] = len(str(node_output))
            return summary

        summary["payload_type"] = type(node_output).__name__
        summary["payload_size"] = len(str(node_output))
        return summary

    def _is_node_failed(self, node_output_summary: Dict[str, Any]) -> bool:
        if not isinstance(node_output_summary, dict):
            return False
        status = str(node_output_summary.get("status") or "").strip().lower()
        if status in {"failed", "error"}:
            return True
        for key in ("error", "reason"):
            value = node_output_summary.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    def _history_preview(
        self,
        history: Optional[List[Dict[str, Any]]],
        *,
        max_items: int = 8,
        max_chars: int = 200,
    ) -> List[Dict[str, Any]]:
        entries = list(history or [])
        preview: List[Dict[str, Any]] = []
        start = max(0, len(entries) - max_items)
        for idx, item in enumerate(entries[start:], start=start):
            if not isinstance(item, dict):
                preview.append({"index": idx, "role": "unknown", "content_preview": str(item)[:max_chars]})
                continue
            content = str(item.get("content") or "").strip()
            if len(content) > max_chars:
                content = content[:max_chars] + "...[truncated]"
            preview.append(
                {
                    "index": idx,
                    "role": str(item.get("role") or "unknown"),
                    "content_preview": content,
                }
            )
        return preview

    async def execute(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        timeout: int = 1800,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> WorkflowResult:
        """
        Execute a workflow.
        """
        task_id = input_data.get("task_id", str(uuid.uuid4()))
        user_id = input_data.get("user_id", "unknown")

        logger.info(f"Manager executing workflow: type={workflow_type}, task={task_id}")

        start_time = time.time()

        try:
            # Get graph WITHOUT passing workspace (to avoid serialization issues)
            # The workspace will be retrieved inside each node when needed
            graph = self._get_graph(workflow_type)

            # Configure LangGraph with thread_id for checkpointing
            config = {"configurable": {"thread_id": task_id}}

            main_graph_context: Optional[MainGraphContext] = None
            if workflow_type == "main":
                input_payload = input_data.get("input") or {}
                main_graph_context = MainGraphContext(
                    user_id=input_data.get("user_id", ""),
                    session_id=input_data.get("session_id", ""),
                    workspace_id=input_data.get("workspace_id", ""),
                    input_context=input_payload.get("context",[]),
                    conversation_history=input_data.get("conversation_history") or [],
                )
                logger.debug(
                    "main workflow context history",
                    phase="execute",
                    task_id=task_id,
                    session_id=input_data.get("session_id") or "default",
                    user_id=input_data.get("user_id") or "unknown",
                    history_count=len(main_graph_context.conversation_history or []),
                    history_preview=self._history_preview(main_graph_context.conversation_history),
                )

            value_events = []
            workspace_id = input_data.get("workspace_id")
            active_node: Optional[str] = None
            active_summary: Dict[str, Any] = {}

            # Run with streaming and timeout
            async def run_graph():
                nonlocal active_node, active_summary
                # Stream both granular node updates (for progress) and full values (for final result).
                astream_kwargs: Dict[str, Any] = {
                    "input": input_data,
                    "config": config,
                    "stream_mode": ["updates", "values"],
                }
                if main_graph_context is not None:
                    astream_kwargs["context"] = main_graph_context

                async for mode, event in graph.astream(**astream_kwargs):
                    if mode == "updates":
                        if progress_callback:
                            if isinstance(event, dict):
                                for node_name, node_output in event.items():
                                    node_summary = self._summarize_node_output(
                                        node_name=node_name,
                                        node_output=node_output,
                                    )
                                    if active_node != node_name:
                                        if active_node:
                                            await progress_callback(
                                                {
                                                    "type": "NODE_COMPLETED",
                                                    "node_name": active_node,
                                                    "node_output": active_summary,
                                                    "workspace_id": workspace_id,
                                                }
                                            )
                                        await progress_callback(
                                            {
                                                "type": "NODE_STARTED",
                                                "node_name": node_name,
                                                "workspace_id": workspace_id,
                                            }
                                        )
                                        active_node = node_name
                                    active_summary = node_summary
                                    if self._is_node_failed(node_summary):
                                        await progress_callback(
                                            {
                                                "type": "NODE_FAILED",
                                                "node_name": node_name,
                                                "node_output": node_summary,
                                                "workspace_id": workspace_id,
                                            }
                                        )
                                        active_node = None
                                        active_summary = {}
                            else:
                                await progress_callback(
                                    {
                                        "type": "WORKFLOW_PROGRESS",
                                        "payload": event,
                                        "workspace_id": workspace_id,
                                    }
                                )
                        continue

                    if mode == "values":
                        value_events.append(event)
                if active_node and progress_callback:
                    await progress_callback(
                        {
                            "type": "NODE_COMPLETED",
                            "node_name": active_node,
                            "node_output": active_summary,
                            "workspace_id": workspace_id,
                        }
                    )
                return value_events[-1] if value_events else {}

            final_state = await asyncio.wait_for(run_graph(), timeout=timeout)

            execution_time_ms = (time.time() - start_time) * 1000

            # Extract checkpoint ID if available (usually thread_id + step)
            # For now returning thread_id as the main identifier

            return WorkflowResult(
                result=final_state,
                checkpoint_id=task_id,  # Simplified for now, LangGraph uses thread_id
                execution_time_ms=execution_time_ms,
            )

        except asyncio.TimeoutError:
            raise WorkflowTimeoutError("Workflow execution timeout")
        except Exception as e:
            raise WorkflowExecutionError(str(e)) from e

    async def resume(
        self,
        checkpoint_id: str,
        additional_input: Optional[Dict[str, Any]] = None,
        timeout: int = 1800,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> WorkflowResult:
        """
        Resume workflow from checkpoint.
        """
        # In this simplified model, checkpoint_id IS the thread_id
        task_id = checkpoint_id

        workflow_type = "main"  # Default, or derive from input/metadata if possible

        # Retrieve state/metadata would happen here in a full impl

        user_id = "unknown"
        if additional_input and "user_id" in additional_input:
            user_id = additional_input["user_id"]


        graph = self._get_graph(workflow_type)
        config = {"configurable": {"thread_id": task_id}}

        main_graph_context: Optional[MainGraphContext] = None
        if workflow_type == "main":
            additional_input = additional_input or {}
            input_payload = additional_input.get("input") or {}
            main_graph_context = MainGraphContext(
                user_id=additional_input.get("user_id"),
                session_id=additional_input.get("session_id"),
                workspace_id=additional_input.get("workspace_id"),
                input_context=input_payload.get("context"),
                conversation_history=additional_input.get("conversation_history") or [],
            )
            logger.debug(
                "main workflow context history",
                phase="resume",
                task_id=task_id,
                session_id=additional_input.get("session_id") or "default",
                user_id=additional_input.get("user_id") or "unknown",
                history_count=len(main_graph_context.conversation_history or []),
                history_preview=self._history_preview(main_graph_context.conversation_history),
            )

        start_time = time.time()
        try:
            value_events = []
            workspace_id = (additional_input or {}).get("workspace_id")
            active_node: Optional[str] = None
            active_summary: Dict[str, Any] = {}

            async def run_resume():
                nonlocal active_node, active_summary
                astream_kwargs: Dict[str, Any] = {
                    "input": additional_input,
                    "config": config,
                    "stream_mode": ["updates", "values"],
                }
                if main_graph_context is not None:
                    astream_kwargs["context"] = main_graph_context

                async for mode, event in graph.astream(**astream_kwargs):
                    if mode == "updates":
                        if progress_callback:
                            if isinstance(event, dict):
                                for node_name, node_output in event.items():
                                    node_summary = self._summarize_node_output(
                                        node_name=node_name,
                                        node_output=node_output,
                                    )
                                    if active_node != node_name:
                                        if active_node:
                                            await progress_callback(
                                                {
                                                    "type": "NODE_COMPLETED",
                                                    "node_name": active_node,
                                                    "node_output": active_summary,
                                                    "workspace_id": workspace_id,
                                                }
                                            )
                                        await progress_callback(
                                            {
                                                "type": "NODE_STARTED",
                                                "node_name": node_name,
                                                "workspace_id": workspace_id,
                                            }
                                        )
                                        active_node = node_name
                                    active_summary = node_summary
                                    if self._is_node_failed(node_summary):
                                        await progress_callback(
                                            {
                                                "type": "NODE_FAILED",
                                                "node_name": node_name,
                                                "node_output": node_summary,
                                                "workspace_id": workspace_id,
                                            }
                                        )
                                        active_node = None
                                        active_summary = {}
                            else:
                                await progress_callback(
                                    {
                                        "type": "WORKFLOW_PROGRESS",
                                        "payload": event,
                                        "workspace_id": workspace_id,
                                    }
                                )
                        continue

                    if mode == "values":
                        value_events.append(event)
                if active_node and progress_callback:
                    await progress_callback(
                        {
                            "type": "NODE_COMPLETED",
                            "node_name": active_node,
                            "node_output": active_summary,
                            "workspace_id": workspace_id,
                        }
                    )
                return value_events[-1] if value_events else {}

            final_state = await asyncio.wait_for(run_resume(), timeout=timeout)

            execution_time_ms = (time.time() - start_time) * 1000

            return WorkflowResult(
                result=final_state,
                checkpoint_id=task_id,
                execution_time_ms=execution_time_ms,
            )
        except asyncio.TimeoutError:
            raise WorkflowTimeoutError("Resume timeout")
        except Exception as e:
            raise WorkflowExecutionError(str(e)) from e

    async def health_check(self) -> bool:
        return await self.checkpoint_saver.health_check()
