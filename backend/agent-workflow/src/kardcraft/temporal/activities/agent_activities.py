"""
Temporal Activities for agent workflows.

This module defines activities that execute LangGraph workflows as Temporal activities.
"""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
import time

from temporalio import activity

from ...llm.context import LLMRuntimeContext, reset_runtime_context, set_runtime_context
from ...workflow.manager import WorkflowManager
from ...services.redis import RedisClient
from ...utils.logger import logger


class AgentActivities:
    """Temporal Activities for executing agent workflows."""

    def __init__(
        self,
        workflow_manager: WorkflowManager,
        redis_client: RedisClient,
    ):
        self.workflow_manager = workflow_manager
        self.redis_client = redis_client
        # Per workflow/node dedupe cache to prevent stream event storms.
        self._progress_cache: Dict[str, Dict[str, Any]] = {}
        # Node lifecycle phase cache: key=task_id:node_name, value=started|completed|failed
        self._node_phase: Dict[str, str] = {}

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
        session_id = input_data.get("session_id")
        task_type = input_data.get("task_type", "main")

        # 立即发送heartbeat，证明Activity已启动
        activity.heartbeat({"status": "initializing", "task_id": task_id})
        activity.logger.info(
            f"Executing agent workflow task_id={task_id} type={task_type}"
        )

        if not task_id or not user_id:
            raise ValueError("task_id and user_id are required")

        input_payload = input_data.get("input", {}) or {}
        workspace_id = (
            str(input_payload.get("session_id") if isinstance(input_payload, dict) else "")
            .strip()
        )
        if not workspace_id:
            raise ValueError("session_id is required")

        # 发送heartbeat表示准备工作完成
        activity.heartbeat({"status": "workspace_ready", "task_id": task_id})

        # Prepare workflow input (不直接传递 workspace 对象，避免序列化问题)
        input_context = input_payload.get("context", {}) if isinstance(input_payload, dict) else {}
        if not isinstance(input_context, dict):
            input_context = {}

        template_id = str(input_context.get("template_id") or "").strip()
        template_profile = str(input_context.get("template_profile") or "").strip()
        template_version_raw = input_context.get("template_version")
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

        if task_type == "main" and not template_id:
            raise ValueError(
                "template_id missing before workflow execution: expected input.context.template_id for main task"
            )

        workflow_input = {
            "task_id": task_id,
            "user_id": user_id,
            "task_type": task_type,
            "config": input_data.get("config", {}),
            "input": input_payload,
            "checkpoint_id": input_data.get("checkpoint_id"),
            "metadata": input_data.get("metadata", {}),
            # 从 input 中提取必需的字段到顶层，以匹配 MainState
            "user_input": input_payload.get("query", ""),
            "topic": input_payload.get("query", ""),  # 用户查询内容
            "session_id": input_payload.get("session_id", ""),
            "workspace_id": workspace_id,
            "conversation_id": input_payload.get("conversation_id", ""),
            "file_ids": input_payload.get("file_ids", []),
            "target_count": input_payload.get("target_count", 10),
            "difficulty_level": input_payload.get("difficulty_level", "medium"),
            # Template context lifted to top-level canonical state fields.
            "template_id": template_id,
            "template_version": template_version,
            "selected_template_profile": template_profile or None,
        }

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
                stream_key = f"stream:events:{task_id}"
                fields = {
                    "task_id": str(task_id),
                    "event_type": "LLM_USAGE",
                    "message": "LLM usage captured",
                    "data": json.dumps(payload, ensure_ascii=False, default=str),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await self.redis_client.stream_add(
                    stream_key=stream_key,
                    fields=fields,
                    maxlen=5000,
                    approximate=False,
                    fail_silently=False,
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
                workflow_error = str(cleaned_result.get("error") or "").strip()
                if workflow_error:
                    normalized_error = workflow_error.lower()
                    pending_questions = cleaned_result.get("pending_questions") or []
                    recoverable_decisions = {
                        "syllabus_decision",
                        "evidence_decision",
                        "clarification_decision",
                        "need_user_input",
                    }
                    if (
                        normalized_error in recoverable_decisions
                        or bool(pending_questions)
                    ):
                        cleaned_result["status"] = "need_user_input"
                        question = str(cleaned_result.get("question") or "").strip()
                        first_pending = ""
                        if pending_questions and isinstance(pending_questions, list):
                            for item in pending_questions:
                                candidate = str(item or "").strip()
                                if candidate:
                                    first_pending = candidate
                                    break
                        if not str(cleaned_result.get("message") or "").strip():
                            cleaned_result["message"] = (
                                question or first_pending or workflow_error
                            )
                    else:
                        raise ValueError(f"Workflow returned error state: {workflow_error}")

            final_cards = cleaned_result.get("final_cards", [])
            approved_cards = cleaned_result.get("approved_cards", [])
            saved_card_ids = cleaned_result.get("saved_card_ids", [])
            intent_type = cleaned_result.get("intent_type")
            raw_status = str(cleaned_result.get("status") or "").strip().lower()
            status = (
                "need_user_input"
                if raw_status in {"need_user_input", "waiting_user_input"}
                else "success"
            )
            message = (
                str(
                    cleaned_result.get("message")
                    or cleaned_result.get("question")
                    or ""
                ).strip()
                if status == "need_user_input"
                else "Workflow completed successfully"
            )
            if status == "need_user_input" and not message:
                message = "Additional user input is required to continue."

            if final_cards:
                message = f"Generated {len(final_cards)} flashcards"
            elif approved_cards:
                message = f"Generated and approved {len(approved_cards)} flashcards"
            elif saved_card_ids:
                message = f"Successfully saved {len(saved_card_ids)} cards"
            else:
                # 检查是否提取到了概念
                knowledge_nodes = cleaned_result.get("knowledge_nodes", [])
                selected_cards = cleaned_result.get("selected_cards", [])
                candidate_cards = cleaned_result.get("candidate_cards", [])

                if not knowledge_nodes or len(knowledge_nodes) == 0:
                    # 没有提取到概念，返回更有意义的提示
                    message = "抱歉，我无法从您的输入中提取到任何概念。请提供更详细的学习内容，例如一段文本、教程或主题的详细描述，这样我才能帮您生成闪卡。"
                elif not selected_cards or len(selected_cards) == 0:
                    # 提取到了概念但没有生成卡片
                    message = f"我已提取到 {len(knowledge_nodes)} 个概念，但未能生成合格的闪卡。请尝试提供更详细的内容或调整难度设置。"
                else:
                    # 尝试从结果中提取文本内容
                    text_candidates = [
                        "output",
                        "text",
                        "response",
                        "content",
                        "result",
                        "answer",
                        "message",
                    ]
                    for key in text_candidates:
                        if key in cleaned_result:
                            val = cleaned_result[key]
                            if isinstance(val, str) and val.strip():
                                lower_val = val.strip().lower()
                                if lower_val in [
                                    "task completed",
                                    "all done",
                                    "done",
                                    "completed",
                                    "success",
                                ]:
                                    continue
                                if len(val.strip()) > 10:
                                    message = val.strip()
                                    break
                            elif isinstance(val, dict):
                                for subkey in text_candidates:
                                    if (
                                        subkey in val
                                        and isinstance(val[subkey], str)
                                        and val[subkey].strip()
                                    ):
                                        subval = val[subkey].strip()
                                        if len(subval) > 10:
                                            message = subval
                                            break
                                if message != "Workflow completed successfully":
                                    break

                # Fallback: 如果以上都没有设置 message
                if message == "Workflow completed successfully" or not message:
                    message = "工作流执行完成，但没有生成任何结果。"

            if intent_type:
                message = f"[{intent_type}] {message}"

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
                event_type="WORKFLOW_COMPLETED",
                message=message,
                session_id=session_id,
            )

            return {
                "schema_version": "task-outcome",
                "status": "success",
                "task_id": task_id,
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
                "result": safe_result,
                "checkpoint_id": result.checkpoint_id if result else task_id,
                "execution_time_ms": execution_time_ms,
                "workflow_type": task_type,
                "final_cards": final_cards,
                "saved_card_ids": saved_card_ids,
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

        async def progress_callback(event_data: Dict[str, Any]):
            await self._publish_progress_event(task_id, event_data)
            activity.heartbeat("Resuming...")

        try:
            async def usage_emitter(payload: Dict[str, Any]) -> None:
                stream_key = f"stream:events:{task_id}"
                fields = {
                    "task_id": str(task_id),
                    "event_type": "LLM_USAGE",
                    "message": "LLM usage captured",
                    "data": json.dumps(payload, ensure_ascii=False, default=str),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await self.redis_client.stream_add(
                    stream_key=stream_key,
                    fields=fields,
                    maxlen=5000,
                    approximate=False,
                    fail_silently=False,
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

        except Exception as e:
            activity.logger.error(f"Agent workflow resume failed: {e}", exc_info=True)
            raise

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

        try:
            # 发布到 Redis Stream 供 SSE 使用
            stream_key = f"stream:events:{task_id}"
            event_payload = {
                "task_id": task_id,
                "event_type": event_type,
                "data": json.dumps(data),
                "timestamp": datetime.utcnow().isoformat(),
            }

            await self.redis_client.stream_add(
                stream_key=stream_key,
                fields=event_payload,
                maxlen=1000,
                approximate=True,
                fail_silently=True,
            )

            return {"status": "success", "event_type": event_type, "task_id": task_id}

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

            stream_key = f"stream:events:{task_id}"
            event_payload = {
                "task_id": task_id,
                "event_type": event_type,
                "data": json.dumps(payload),
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            if node_name:
                event_payload["node_name"] = node_name
            if workspace_id:
                event_payload["workspace_id"] = workspace_id

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

            await self.redis_client.stream_add(
                stream_key=stream_key,
                fields=event_payload,
                maxlen=1000,
                approximate=False,
                fail_silently=True,
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

        await self.publish_workflow_event(
            {
                "task_id": task_id,
                "event_type": event_type,
                "data": terminal_payload,
            }
        )
        await self.publish_workflow_event(
            {
                "task_id": task_id,
                "event_type": "done",
                "data": {
                    "message": "Stream end",
                    "task_id": task_id,
                    "workspace_id": session_id or "",
                    "session_id": session_id or "",
                },
            }
        )

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
