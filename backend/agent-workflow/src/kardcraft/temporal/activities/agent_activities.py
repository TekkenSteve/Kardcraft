"""
Temporal Activities for agent workflows.

This module defines activities that execute LangGraph workflows as Temporal activities.
"""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import time
import uuid

from temporalio import activity

from ...llm.context import LLMRuntimeContext, reset_runtime_context, set_runtime_context
from ...llm.usage_event import validate_usage_recorded_event
from ...workflow.manager import WorkflowManager
from ...services.redis import RedisClient
from ...services.workflow_event_bus import EventContext, WorkflowEventBus
from ...utils.conversation_history import normalize_conversation_history
from ...utils.logger import logger


class AgentActivities:
    """Temporal Activities for executing agent workflows."""

    def __init__(
        self,
        workflow_manager: WorkflowManager,
        redis_client: RedisClient,
        event_bus: Optional[WorkflowEventBus] = None,
    ):
        self.workflow_manager = workflow_manager
        self.redis_client = redis_client
        self.event_bus = event_bus or WorkflowEventBus()
        # Per workflow/node dedupe cache to prevent stream event storms.
        self._progress_cache: Dict[str, Dict[str, Any]] = {}
        # Node lifecycle phase cache: key=task_id:node_name, value=started|completed|failed
        self._node_phase: Dict[str, str] = {}
        self._event_contexts: Dict[str, EventContext] = {}

    async def _ensure_redis_ready(self) -> None:
        # Ensure Redis initializes in the same event loop that executes activities.
        await self.redis_client.initialize_async()

    def _build_event_context(
        self,
        *,
        task_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> EventContext:
        try:
            info = activity.info()
            workflow_id = str(getattr(info, "workflow_id", "") or "unknown-workflow")
            run_id = str(
                getattr(info, "workflow_run_id", "")
                or getattr(info, "run_id", "")
                or "unknown-run"
            )
        except Exception:
            workflow_id = "unknown-workflow"
            run_id = "unknown-run"
        return EventContext(
            task_id=str(task_id),
            session_id=str(session_id or "") or None,
            user_id=str(user_id or "") or None,
            workflow_id=workflow_id,
            run_id=run_id,
        )

    @activity.defn(name="execute_agent_workflow")
    async def execute_agent_workflow(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute LangGraph workflow as Temporal activity.
        Temporal automatically handles retries, timeouts, and state persistence.
        """
        task_id = input_data.get("task_id")
        user_id = input_data.get("user_id")
        task_type = input_data.get("task_type", "main")
        config = input_data.get("config", {})
        metadata = input_data.get("metadata", {})

        # Send the heartbeat immediately to prove the activity has started
        activity.heartbeat({"status": "initializing", "task_id": task_id})
        activity.logger.info(
            f"Executing agent workflow task_id={task_id} type={task_type}"
        )

        if not task_id or not user_id:
            raise ValueError("task_id and user_id are required")
        await self._ensure_redis_ready()

        # 必须字段解析（Lower Bound）
        input_payload = input_data.get("input")
        if not isinstance(input_payload, dict):
            raise ValueError("input must be an object")

        session_id = str(input_payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required in input.session_id")
        workspace_id = session_id

        # 可选字段解析（Upper Bound by task_type）
        input_context = input_payload.get("context", {})
        if not isinstance(input_context, dict):
            input_context = {}

        template_id = (
            str(input_context.get("template_id") or "").strip()
            if task_type == "main"
            else str(input_payload.get("template_id") or "").strip()
        )
        template_profile = str(input_context.get("template_profile") or "").strip()
        template_version_raw = (
            input_context.get("template_version")
            if task_type == "main"
            else input_payload.get("template_version")
        )
        try:
            template_version = int(template_version_raw or 0)
        except Exception:
            template_version = 0

        logger.info(
            "execute_agent_workflow input decoded",
            task_id=task_id,
            task_type=task_type,
            has_input=isinstance(input_payload, dict),
            has_context=isinstance(input_payload, dict) and isinstance(input_payload.get("context"), dict),
            template_id=template_id,
            template_version=template_version,
            template_profile=template_profile or None,
        )

        if task_type not in {"main", "card_template"}:
            raise ValueError(f"unsupported task_type: {task_type}")
        if task_type == "main":
            query = str(input_payload.get("query") or "").strip()
            if not query:
                raise ValueError("query is required in input.query for main task")
            if not template_id:
                raise ValueError("template_id is required in input.context.template_id for main task")
        else:
            query = str(input_payload.get("query") or "").strip()
        if task_type == "card_template" and not template_id:
            raise ValueError("template_id is required in input.template_id for card_template task")

        conversation_history = normalize_conversation_history(
            input_payload.get("conversation_history")
        )

        workflow_input = {
            "task_id": task_id,
            "user_id": user_id,
            "session_id": session_id,
            "task_type": task_type,
            "config": config,
            "metadata": metadata,
            "input": input_payload,
            "workspace_id": workspace_id,
            "user_input": query,
            "conversation_history": conversation_history,
            "file_ids": input_payload.get("file_ids", []),
            "target_count": input_payload.get("target_count", 10),
            "difficulty_level": input_payload.get("difficulty_level", "medium"),
            "template_id": template_id,
            "template_version": template_version,
            "selected_template_profile": template_profile or None,
            "clarification_responses": input_payload.get("clarification_responses") or {},
        }
        event_ctx = self._build_event_context(
            task_id=str(task_id),
            session_id=session_id,
            user_id=str(user_id),
        )
        self._event_contexts[str(task_id)] = event_ctx
        await self.event_bus.mark_task_running(str(task_id))

        # 增强的progress callback，确保定期heartbeat
        last_heartbeat_time = [0.0]

        async def progress_callback(event_data: Dict[str, Any]):
            import asyncio

            current_time = asyncio.get_event_loop().time()

            # 每10秒至少heartbeat一次（防止30s timeout）
            if current_time - last_heartbeat_time[0] > 10:
                activity.heartbeat(
                    {
                        "status": "processing",
                        "step": event_data.get("type", "unknown"),
                        "timestamp": current_time,
                        "task_id": task_id,
                    }
                )
                last_heartbeat_time[0] = current_time

            # 发布到Redis供前端实时查看
            await self._publish_progress_event(task_id, event_data)

        try:
            # 发送heartbeat表示开始执行LangGraph
            activity.heartbeat({"status": "running_langgraph", "task_id": task_id})

            async def usage_emitter(payload: Dict[str, Any]) -> None:
                event_payload = {
                    "event_id": str(uuid.uuid4()),
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "task_id": str(task_id),
                    "workflow_id": str(event_ctx.workflow_id),
                    "session_id": str(session_id or ""),
                    "user_id": str(user_id or ""),
                    "usage": payload,
                }
                ok, reason = validate_usage_recorded_event(event_payload)
                if not ok:
                    raise ValueError(f"invalid usage payload: {reason}")
                await self.event_bus.publish_usage(
                    ctx=event_ctx,
                    payload=event_payload,
                )

            llm_ctx_token = set_runtime_context(
                LLMRuntimeContext(
                    task_id=str(task_id),
                    session_id=str(workspace_id),
                    user_id=str(user_id),
                    usage_emitter=usage_emitter,
                )
            )

            # Execute LangGraph workflow
            # Note: We rely on Temporal's StartToCloseTimeout, so we don't need a strict internal timeout unless desired.
            try:
                result = await self.workflow_manager.execute(
                    workflow_type=task_type,
                    input_data=workflow_input,
                    timeout=1800,  # Keep internal timeout as safety net
                    progress_callback=progress_callback,
                )
            finally:
                reset_runtime_context(llm_ctx_token)

            # 完成时发送heartbeat
            activity.heartbeat({"status": "completed", "task_id": task_id})

            execution_time_ms = (
                int(result.execution_time_ms)
                if hasattr(result, "execution_time_ms")
                else 0
            )

            cleaned_result = (
                self._deep_clean_result(result.result) if result.result else {}
            )
            if isinstance(cleaned_result, dict):
                self._validate_clarification_contract(cleaned_result)
                raw_status = str(cleaned_result.get("status") or "").strip().lower()
                workflow_error = str(cleaned_result.get("error") or "").strip()
                if workflow_error:
                    if self._is_need_user_input_result(cleaned_result):
                        cleaned_result["status"] = "need_user_input"
                        if not str(cleaned_result.get("message") or "").strip():
                            cleaned_result["message"] = (
                                str(cleaned_result.get("question") or "").strip()
                                or self._extract_first_pending_question(
                                    cleaned_result.get("pending_questions")
                                )
                                or workflow_error
                            )
                    elif raw_status == "failed":
                        # Business-level failures (e.g. quality threshold not met)
                        # should be returned as failed outcomes, not raised as activity exceptions.
                        if not str(cleaned_result.get("message") or "").strip():
                            cleaned_result["message"] = workflow_error
                    else:
                        raise ValueError(f"Workflow returned error state: {workflow_error}")

            final_cards = cleaned_result.get("final_cards", [])
            approved_cards = cleaned_result.get("approved_cards", [])
            saved_card_ids = cleaned_result.get("saved_card_ids", [])
            intent_type = cleaned_result.get("intent_type")
            raw_status = str(cleaned_result.get("status") or "").strip().lower()
            if raw_status in {"success", "need_user_input", "failed"}:
                status = raw_status
            else:
                status = "need_user_input" if self._is_need_user_input_result(cleaned_result) else "success"
            message = self._resolve_outcome_message(
                cleaned_result=cleaned_result,
                status=status,
                final_cards=final_cards,
                approved_cards=approved_cards,
                saved_card_ids=saved_card_ids,
            )

            if intent_type:
                message = f"[{intent_type}] {message}"

            template_id_for_workspace = str(cleaned_result.get("template_id") or template_id or "").strip()
            supported_question_types_raw = cleaned_result.get("template_profiles") or []
            if not isinstance(supported_question_types_raw, list):
                supported_question_types_raw = []
            supported_question_types: list[str] = []
            for item in supported_question_types_raw:
                value = str(item or "").strip()
                if value and value not in supported_question_types:
                    supported_question_types.append(value)
            selected_question_type = str(
                cleaned_result.get("selected_template_profile")
                or cleaned_result.get("template_default_profile")
                or template_profile
                or ""
            ).strip()
            outcome_metadata = {
                "template_id": template_id_for_workspace,
                "supported_question_types": supported_question_types,
                "selected_question_type": selected_question_type,
            }

            safe_result = {
                "workflow_completed": True,
                "task_id": task_id,
                "user_id": user_id,
                "workflow_type": task_type,
                "execution_time_ms": execution_time_ms,
                "status": status,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                "intent_type": intent_type,
                "summary": {
                    "workflow_type": task_type,
                    "processing_complete": True,
                    "has_result": result is not None,
                    "final_cards_count": len(final_cards),
                    "approved_cards_count": len(approved_cards),
                    "saved_cards_count": len(saved_card_ids),
                    "checkpoint_available": bool(result and result.checkpoint_id)
                    if result
                    else False,
                },
                "data": cleaned_result,
            }

            # 验证结果确实可序列化
            try:
                json.dumps(safe_result)
                activity.logger.info(
                    f"✅ Safe result created and verified serializable for task {task_id}"
                )
            except Exception as e:
                activity.logger.error(f"❌ Even safe result failed serialization: {e}")
                # 最后的备选方案
                safe_result = {
                    "status": "completed",
                    "task_id": task_id,
                    "message": "Workflow completed but result serialization failed",
                }

            # Emit terminal realtime events so frontend status/timeline can converge without page refresh.
            await self._publish_terminal_events(
                task_id=task_id,
                event_type="WORKFLOW_FAILED" if status == "failed" else "WORKFLOW_COMPLETED",
                message=message,
                session_id=session_id,
            )

            return {
                "schema_version": "task-outcome",
                "status": status,
                "task_id": task_id,
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
                "metadata": outcome_metadata,
                "result": safe_result,
                "checkpoint_id": result.checkpoint_id if result else task_id,
                "execution_time_ms": execution_time_ms,
                "workflow_type": task_type,
                "final_cards": final_cards,
                "saved_card_ids": saved_card_ids,
            }

        except asyncio.CancelledError:
            activity.logger.info(
                f"Agent workflow cancelled by user/system task_id={task_id}"
            )
            try:
                await self.event_bus.mark_task_cancelling(str(task_id))
                await self._publish_terminal_events(
                    task_id=task_id,
                    event_type="WORKFLOW_CANCELLED",
                    message="Workflow cancelled",
                    session_id=session_id,
                )
            except Exception:
                pass
            return {
                "schema_version": "task-outcome",
                "status": "cancelled",
                "task_id": task_id,
                "user_id": user_id,
                "session_id": session_id,
                "message": "Workflow cancelled",
                "metadata": {},
                "result": {
                    "workflow_completed": False,
                    "task_id": task_id,
                    "user_id": user_id,
                    "workflow_type": task_type,
                    "status": "cancelled",
                    "message": "Workflow cancelled",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                "checkpoint_id": task_id,
                "execution_time_ms": 0,
                "workflow_type": task_type,
                "final_cards": [],
                "saved_card_ids": [],
            }
        except Exception as e:
            activity.logger.error(f"Agent workflow failed: {e}", exc_info=True)
            # Best-effort terminal event on failures; do not swallow original exception.
            try:
                await self._publish_terminal_events(
                    task_id=task_id,
                    event_type="WORKFLOW_FAILED",
                    message=str(e) or "Workflow failed",
                    session_id=session_id,
                )
            except Exception:
                pass
            # We raise the exception so Temporal marks the activity as failed and can retry if configured
            raise
        finally:
            self._event_contexts.pop(str(task_id), None)

    @activity.defn(name="resume_agent_workflow")
    async def resume_agent_workflow(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resume LangGraph workflow from checkpoint.
        """
        task_id = input_data.get("task_id")
        checkpoint_id = input_data.get("checkpoint_id")
        session_id = input_data.get("session_id")
        user_id = input_data.get("user_id")
        activity.logger.info(
            f"Resuming workflow task_id={task_id} checkpoint={checkpoint_id}"
        )

        if not task_id or not checkpoint_id:
            raise ValueError("task_id and checkpoint_id are required")
        await self._ensure_redis_ready()
        event_ctx = self._build_event_context(
            task_id=str(task_id),
            session_id=str(session_id or ""),
            user_id=str(user_id or ""),
        )
        self._event_contexts[str(task_id)] = event_ctx
        await self.event_bus.mark_task_running(str(task_id))

        async def progress_callback(event_data: Dict[str, Any]):
            await self._publish_progress_event(task_id, event_data)
            activity.heartbeat("Resuming...")

        try:
            async def usage_emitter(payload: Dict[str, Any]) -> None:
                event_payload = {
                    "event_id": str(uuid.uuid4()),
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "task_id": str(task_id),
                    "workflow_id": str(event_ctx.workflow_id),
                    "session_id": str(session_id or ""),
                    "user_id": str(user_id or ""),
                    "usage": payload,
                }
                ok, reason = validate_usage_recorded_event(event_payload)
                if not ok:
                    raise ValueError(f"invalid usage payload: {reason}")
                await self.event_bus.publish_usage(
                    ctx=event_ctx,
                    payload=event_payload,
                )

            llm_ctx_token = set_runtime_context(
                LLMRuntimeContext(
                    task_id=str(task_id),
                    session_id=str(session_id or ""),
                    user_id=str(user_id or ""),
                    usage_emitter=usage_emitter,
                )
            )
            try:
                result = await self.workflow_manager.resume(
                    checkpoint_id=checkpoint_id,
                    additional_input=input_data.get("additional_input", {}),
                    timeout=1800,
                    progress_callback=progress_callback,
                )
            finally:
                reset_runtime_context(llm_ctx_token)

            execution_time_ms = (
                int(result.execution_time_ms)
                if hasattr(result, "execution_time_ms")
                else 0
            )

            return {
                "status": "success",
                "task_id": task_id,
                "result": result.result,
                "checkpoint_id": result.checkpoint_id,
                "execution_time_ms": execution_time_ms,
            }

        except asyncio.CancelledError:
            activity.logger.info(f"Agent workflow resume cancelled task_id={task_id}")
            try:
                await self.event_bus.mark_task_cancelling(str(task_id))
            except Exception:
                pass
            return {
                "status": "cancelled",
                "task_id": task_id,
                "checkpoint_id": checkpoint_id,
                "execution_time_ms": 0,
                "message": "Workflow resume cancelled",
            }
        except Exception as e:
            activity.logger.error(f"Agent workflow resume failed: {e}", exc_info=True)
            raise
        finally:
            self._event_contexts.pop(str(task_id), None)

    @activity.defn(name="health_check_activity")
    async def health_check_activity(self) -> Dict[str, Any]:
        """Simple health check activity."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
        }

    @activity.defn(name="publish_workflow_event")
    async def publish_workflow_event(
        self, event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        发布工作流事件到 Redis (替代 Go 的 PublishWorkflowEventActivity)
        """
        task_id = event_data.get("task_id")
        event_type = event_data.get("event_type")
        data = event_data.get("data", {})

        activity.logger.info(
            f"Publishing workflow event: {event_type} for task {task_id}"
        )
        data = data if isinstance(data, dict) else {}
        event_ctx = self._event_contexts.get(str(task_id)) or self._build_event_context(
            task_id=str(task_id),
            session_id=str(data.get("workspace_id") or data.get("session_id") or ""),
            user_id=None,
        )

        try:
            normalized_event_type = str(event_type or "").strip()
            payload = {
                "task_id": task_id,
                "event_type": normalized_event_type or "WORKFLOW_PROGRESS",
                "timestamp": datetime.utcnow().isoformat(),
                **data,
            }
            if normalized_event_type.lower() == "done":
                accepted = await self.event_bus.publish_done(
                    ctx=event_ctx,
                    message=str(data.get("message") or "Stream end"),
                )
            elif normalized_event_type.upper() in {
                "WORKFLOW_COMPLETED",
                "WORKFLOW_FAILED",
                "WORKFLOW_CANCELLED",
            }:
                accepted = await self.event_bus.publish_terminal(
                    ctx=event_ctx,
                    event_type=normalized_event_type.upper(),
                    message=str(data.get("message") or normalized_event_type),
                    payload=payload,
                )
            else:
                accepted = await self.event_bus.publish_progress(
                    ctx=event_ctx,
                    payload=payload,
                )
            return {
                "status": "success" if accepted else "dropped",
                "event_type": normalized_event_type or "WORKFLOW_PROGRESS",
                "task_id": task_id,
            }

        except Exception as e:
            activity.logger.error(f"Failed to publish workflow event: {e}")
            return {"status": "error", "error": str(e)}

    async def _publish_progress_event(self, task_id: str, data: Dict[str, Any]):
        """Publish progress event to Redis Stream for Frontend SSE."""
        try:
            cleaned_data = self._clean_event_data(data)
            if isinstance(cleaned_data, dict):
                payload: Dict[str, Any] = dict(cleaned_data)
            else:
                payload = {"payload": cleaned_data}

            raw_type = payload.get("type") or payload.get("event_type")
            event_type = str(raw_type or "WORKFLOW_PROGRESS").strip().upper()
            if not event_type:
                event_type = "WORKFLOW_PROGRESS"

            node_name_raw = payload.get("node_name")
            node_name = str(node_name_raw or "").strip() if node_name_raw is not None else ""
            is_node_lifecycle = event_type in {"NODE_STARTED", "NODE_COMPLETED", "NODE_FAILED"}
            if is_node_lifecycle and not node_name:
                return

            node_output = payload.get("node_output")
            if not isinstance(node_output, dict):
                node_output = {}
            payload["node_output"] = node_output

            explicit_message = payload.get("message") or payload.get("progress_message")
            if isinstance(explicit_message, str) and explicit_message.strip():
                message = explicit_message.strip()
            elif event_type == "NODE_STARTED":
                message = f"{node_name} started"
            elif event_type == "NODE_COMPLETED":
                message = f"{node_name} completed"
            elif event_type == "NODE_FAILED":
                message = f"{node_name} failed"
            else:
                message = "Workflow progressing"

            workspace_id_raw = payload.get("workspace_id") or payload.get("workspace")
            workspace_id = str(workspace_id_raw or "").strip()

            if is_node_lifecycle:
                node_key = f"{task_id}:{node_name}"
                prev_phase = self._node_phase.get(node_key, "")
                if event_type == "NODE_STARTED":
                    if prev_phase == "started":
                        return
                    self._node_phase[node_key] = "started"
                elif event_type in {"NODE_COMPLETED", "NODE_FAILED"}:
                    if prev_phase not in {"started", ""}:
                        return
                    self._node_phase[node_key] = (
                        "completed" if event_type == "NODE_COMPLETED" else "failed"
                    )

            payload["event_type"] = event_type
            payload["message"] = message
            if node_name:
                payload["node_name"] = node_name
                payload["event_name"] = node_name
            if workspace_id:
                payload["workspace_id"] = workspace_id

            cache_key = f"{task_id}:{event_type}:{node_name or '_'}"
            now_ts = time.monotonic()
            cache = self._progress_cache.get(cache_key) or {}
            last_payload_fingerprint = str(cache.get("fingerprint") or "")
            fingerprint = f"{event_type}|{node_name}|{message}|{workspace_id}"
            last_emit_ts = float(cache.get("emit_ts") or 0.0)
            elapsed = now_ts - last_emit_ts
            if fingerprint == last_payload_fingerprint and elapsed < 1.0:
                cache["suppressed"] = int(cache.get("suppressed") or 0) + 1
                cache["last_seen_ts"] = now_ts
                self._progress_cache[cache_key] = cache
                return

            event_ctx = self._event_contexts.get(str(task_id))
            if event_ctx is None:
                event_ctx = self._build_event_context(
                    task_id=str(task_id),
                    session_id=str(workspace_id or ""),
                    user_id=None,
                )
                self._event_contexts[str(task_id)] = event_ctx

            await self.event_bus.publish_progress(
                ctx=event_ctx,
                payload=payload,
            )
            self._progress_cache[cache_key] = {
                "fingerprint": fingerprint,
                "emit_ts": now_ts,
                "last_seen_ts": now_ts,
                "suppressed": 0,
            }
            # Guard memory growth for long-running workers.
            if len(self._progress_cache) > 5000:
                cutoff = now_ts - 900.0
                self._progress_cache = {
                    k: v
                    for k, v in self._progress_cache.items()
                    if float(v.get("last_seen_ts") or 0.0) >= cutoff
                }
            if len(self._node_phase) > 5000:
                # Keep lifecycle cache bounded; phases are only needed in short horizon.
                self._node_phase = {
                    k: v
                    for k, v in self._node_phase.items()
                    if k.startswith(f"{task_id}:")
                }
        except Exception as e:
            logger.warning(f"Failed to publish progress event: {e}")

    async def _publish_terminal_events(
        self,
        task_id: str,
        event_type: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Publish terminal realtime events so frontend can close status without waiting for refresh.
        Event order is: terminal event -> done.
        """
        terminal_payload = {
            "message": message,
            "task_id": task_id,
        }
        if session_id:
            terminal_payload["workspace_id"] = session_id
            terminal_payload["session_id"] = session_id
        event_ctx = self._event_contexts.get(str(task_id)) or self._build_event_context(
            task_id=str(task_id),
            session_id=str(session_id or ""),
            user_id=None,
        )
        await self.event_bus.publish_terminal(
            ctx=event_ctx,
            event_type=event_type,
            message=message,
            payload=terminal_payload,
        )
        await self.event_bus.publish_done(
            ctx=event_ctx,
            message="Stream end",
        )

    def _extract_first_pending_question(self, pending_questions: Any) -> str:
        if not isinstance(pending_questions, list):
            return ""
        for item in pending_questions:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("question_text") or "").strip()
            if candidate:
                return candidate
        return ""

    def _is_need_user_input_result(self, cleaned_result: Dict[str, Any]) -> bool:
        raw_status = str(cleaned_result.get("status") or "").strip().lower()
        return raw_status == "need_user_input"

    def _resolve_outcome_message(
        self,
        *,
        cleaned_result: Dict[str, Any],
        status: str,
        final_cards: Any,
        approved_cards: Any,
        saved_card_ids: Any,
    ) -> str:
        if status == "need_user_input":
            return (
                str(cleaned_result.get("message") or "").strip()
                or self._extract_first_pending_question(cleaned_result.get("pending_questions"))
                or "Additional user input is required to continue."
            )
        if status == "failed":
            return (
                str(cleaned_result.get("message") or "").strip()
                or str(cleaned_result.get("error") or "").strip()
                or "Workflow failed"
            )

        if final_cards:
            return f"Generated {len(final_cards)} flashcards"
        if approved_cards:
            return f"Generated and approved {len(approved_cards)} flashcards"
        if saved_card_ids:
            return f"Successfully saved {len(saved_card_ids)} cards"

        message = str(cleaned_result.get("message") or "").strip()
        if message and message.lower() not in {"task completed", "all done", "done", "completed", "success"}:
            return message
        return "Workflow completed successfully"

    def _validate_clarification_contract(self, cleaned_result: Dict[str, Any]) -> None:
        status = str(cleaned_result.get("status") or "").strip().lower()
        if status not in {"", "success", "need_user_input", "failed"}:
            raise ValueError(f"Invalid status in workflow result: {status}")
        if status != "need_user_input":
            return

        clarification_state = str(cleaned_result.get("clarification_state") or "").strip().lower()
        if clarification_state not in {"collecting", "resolved", "exhausted"}:
            raise ValueError("need_user_input result must include valid clarification_state")

        pending_questions = cleaned_result.get("pending_questions")
        if not isinstance(pending_questions, list):
            raise ValueError("need_user_input result requires pending_questions as list")

        if clarification_state == "collecting" and len(pending_questions) == 0:
            raise ValueError("collecting clarification_state requires non-empty pending_questions")

        if clarification_state == "exhausted":
            termination_reason = str(cleaned_result.get("termination_reason") or "").strip().lower()
            if termination_reason != "exhausted":
                raise ValueError("exhausted clarification_state requires termination_reason=exhausted")

        for idx, item in enumerate(pending_questions):
            if not isinstance(item, dict):
                raise ValueError(f"pending_questions[{idx}] must be an object")
            question_id = str(item.get("id") or "").strip()
            question_text = str(item.get("question_text") or "").strip()
            info_type = str(item.get("info_type") or "").strip()
            required = item.get("required")
            input_type = str(item.get("input_type") or "").strip()
            options = item.get("options")
            if not question_id:
                raise ValueError(f"pending_questions[{idx}].id is required")
            if not question_text:
                raise ValueError(f"pending_questions[{idx}].question_text is required")
            if not info_type:
                raise ValueError(f"pending_questions[{idx}].info_type is required")
            if not isinstance(required, bool):
                raise ValueError(f"pending_questions[{idx}].required must be boolean")
            if input_type not in {"free_text", "single_select", "multi_select", "file_upload"}:
                raise ValueError(f"pending_questions[{idx}].input_type is invalid")
            if not isinstance(options, list):
                raise ValueError(f"pending_questions[{idx}].options must be an array")

    def _deep_clean_result(self, data: Any, depth: int = 0, max_depth: int = 10) -> Any:
        """
        深度清理结果数据，移除所有不可序列化的对象
        """
        if depth > max_depth:
            return "MAX_DEPTH_REACHED"

        if data is None:
            return None
        elif isinstance(data, (str, int, float, bool)):
            return data
        elif isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # 跳过已知的不可序列化字段
                if key in ["workspace", "user_workspace", "workspace_service"]:
                    continue

                # 检查值的类型
                if hasattr(value, "__class__"):
                    class_name = str(value.__class__)
                    # 跳过所有 UserWorkspace 相关的对象
                    if any(
                        pattern in class_name
                        for pattern in [
                            "UserWorkspace",
                            "Workspace",
                            "Database",
                            "Connection",
                            "Pool",
                        ]
                    ):
                        continue

                # 递归清理
                try:
                    cleaned_value = self._deep_clean_result(value, depth + 1, max_depth)
                    if cleaned_value is not None:
                        result[key] = cleaned_value
                except Exception as e:
                    # 如果清理失败，跳过这个字段
                    activity.logger.warning(f"Failed to clean field '{key}': {e}")
                    continue

            return result
        elif isinstance(data, (list, tuple)):
            result = []
            for item in data:
                # 检查项目类型
                if hasattr(item, "__class__"):
                    class_name = str(item.__class__)
                    if any(
                        pattern in class_name
                        for pattern in [
                            "UserWorkspace",
                            "Workspace",
                            "Database",
                            "Connection",
                            "Pool",
                        ]
                    ):
                        continue

                try:
                    cleaned_item = self._deep_clean_result(item, depth + 1, max_depth)
                    if cleaned_item is not None:
                        result.append(cleaned_item)
                except Exception:
                    continue

            return result
        else:
            # 对于其他类型，检查是否可序列化
            if hasattr(data, "__class__"):
                class_name = str(data.__class__)
                if any(
                    pattern in class_name
                    for pattern in [
                        "UserWorkspace",
                        "Workspace",
                        "Database",
                        "Connection",
                        "Pool",
                    ]
                ):
                    return None

            # 尝试序列化测试
            try:
                json.dumps(data)
                return data
            except (TypeError, ValueError):
                # 如果不能序列化，尝试转换为字符串
                try:
                    return str(data)
                except:
                    return None

    def _clean_result_data(self, data: Any) -> Any:
        """
        递归清理结果数据，移除不可序列化的对象
        """
        if data is None:
            return None
        elif isinstance(data, (str, int, float, bool)):
            return data
        elif isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # 跳过 workspace 和其他不可序列化的对象
                if key == "workspace":
                    continue
                # 检查值是否为 UserWorkspace 类型
                if hasattr(value, "__class__") and "UserWorkspace" in str(
                    value.__class__
                ):
                    continue
                # 跳过其他复杂对象
                if hasattr(value, "__dict__") and not isinstance(
                    value, (str, int, float, bool, list, dict, tuple)
                ):
                    continue
                result[key] = self._clean_result_data(value)
            return result
        elif isinstance(data, (list, tuple)):
            return [
                self._clean_result_data(item)
                for item in data
                if not (
                    hasattr(item, "__class__")
                    and "UserWorkspace" in str(item.__class__)
                )
            ]
        else:
            # 对于其他类型，检查是否为 UserWorkspace
            if hasattr(data, "__class__") and "UserWorkspace" in str(data.__class__):
                return None
            # 尝试转换为字符串或跳过
            try:
                return str(data)
            except:
                return None

    def _clean_event_data(self, data: Any) -> Any:
        """
        递归清理事件数据，移除不可序列化的对象
        """
        if data is None:
            return None
        elif isinstance(data, (str, int, float, bool)):
            return data
        elif isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # 跳过 workspace 和其他不可序列化的对象
                if key == "workspace":
                    continue
                # 检查值是否为 UserWorkspace 类型
                if hasattr(value, "__class__") and "UserWorkspace" in str(
                    value.__class__
                ):
                    continue
                # 跳过其他复杂对象
                if hasattr(value, "__dict__") and not isinstance(
                    value, (str, int, float, bool, list, dict, tuple)
                ):
                    continue
                result[key] = self._clean_event_data(value)
            return result
        elif isinstance(data, (list, tuple)):
            return [
                self._clean_event_data(item)
                for item in data
                if not (
                    hasattr(item, "__class__")
                    and "UserWorkspace" in str(item.__class__)
                )
            ]
        else:
            # 对于其他类型，检查是否为 UserWorkspace
            if hasattr(data, "__class__") and "UserWorkspace" in str(data.__class__):
                return None
            # 尝试转换为字符串或跳过
            try:
                return str(data)
            except:
                return None
