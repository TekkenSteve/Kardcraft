# ragix/core/ragix_client.py
"""
Ragix 统一客户端（LightRAG Server 版本）

最小可用：
- upload 文档
- insert 文本
- query
- delete session(workspace)
"""

import asyncio
import mimetypes
import os
import tempfile
from typing import List, Dict, Any, Optional, Set

from .container import RagixContainer
from .lightrag_service import LightRAGRESTClient, LightRAGServiceManager
from .._types import Answer
from ..implementations.preprocessors import DocumentPipeline, PreprocessConfig
from ..implementations.pipelines import QueryPipeline, QueryPipelineConfig
from kardcraft.utils.logger import logger


class RagixClient:
    """Ragix 客户端 - 只代理 LightRAG REST Server"""

    def __init__(self):
        self.container = RagixContainer()
        self._lightrag_manager: Optional[LightRAGServiceManager] = None
        self._initialized = False
        self._preprocess = DocumentPipeline(
            PreprocessConfig(emit_original=True, emit_metadata=False)
        )
        self._query_pipeline = QueryPipeline(QueryPipelineConfig())
        self._indexed_files: Set[str] = set()

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self.container.initialize()
        manager = self.container.get_component("lightrag_service")
        if not isinstance(manager, LightRAGServiceManager):
            raise RuntimeError("LightRAG service manager not available")

        self._lightrag_manager = manager
        self._initialized = True

    def _get_client(self, workspace: Optional[str]) -> LightRAGRESTClient:
        if not self._initialized or self._lightrag_manager is None:
            raise RuntimeError("Ragix client not initialized")
        return self._lightrag_manager.get_instance(workspace or "default")

    async def add_document(
        self,
        file_id: str,
        user_id: str,
        session_id: Optional[str] = None,
        parser_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """从 file-storage 拉取文件并上传索引（返回 track_id）"""
        if not self._initialized:
            await self.initialize()

        from kardcraft.utils.file_storage_client import download_conversation_file

        content_bytes, metadata = await download_conversation_file(user_id, file_id)
        filename = None
        if metadata and metadata.custom_meta:
            filename = metadata.custom_meta.get("original_filename")
        if not filename:
            filename = f"{file_id}"

        client = self._get_client(session_id)
        return await self._preprocess_and_insert(
            client,
            filename,
            content_bytes,
            session_id=session_id,
            parser_params=parser_params,
        )

    async def add_local_document(
        self,
        file_path: str,
        session_id: Optional[str] = None,
        parser_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """上传本地文件并索引（返回 track_id）"""
        if not self._initialized:
            await self.initialize()

        client = self._get_client(session_id)
        with open(file_path, "rb") as f:
            content_bytes = f.read()
        filename = os.path.basename(file_path)
        return await self._preprocess_and_insert(
            client,
            filename,
            content_bytes,
            session_id=session_id,
            parser_params=parser_params,
        )

    async def add_documents(
        self,
        file_ids: List[str],
        user_id: str,
        session_id: Optional[str] = None,
        parser_params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """批量上传并索引（返回 track_id 列表）"""
        if not file_ids:
            return []

        results: List[str] = []
        for file_id in file_ids:
            results.append(
                await self.add_document(
                    file_id,
                    user_id,
                    session_id=session_id,
                    parser_params=parser_params,
                )
            )
        return results

    async def insert_text(
        self,
        content: str,
        session_id: Optional[str] = None,
        file_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """插入文本内容"""
        if not self._initialized:
            await self.initialize()

        client = self._get_client(session_id)
        return await client.insert_text(content, workspace=session_id, file_source=file_source)

    async def query(
        self,
        question: str,
        session_id: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        top_k: int = 10,
        mode: str = "mix",
        modes: Optional[List[str]] = None,
    ) -> Answer:
        """Query LightRAG (workspace isolated by session_id)"""
        if not self._initialized:
            await self.initialize()

        if file_ids and user_id:
            await self._ensure_files_indexed(session_id, file_ids, user_id)

        client = self._get_client(session_id)
        return await self._query_pipeline.query(
            client,
            question,
            session_id=session_id,
            mode=mode,
            modes=modes,
            top_k=top_k,
            include_references=True,
        )

    async def delete_session(self, session_id: str) -> bool:
        """删除 session/workspace"""
        if not self._initialized:
            await self.initialize()

        client = self._get_client(session_id)
        result = await client.drop_workspace(session_id)
        return result.get("status") == "success"

    async def _ensure_files_indexed(
        self, session_id: Optional[str], file_ids: List[str], user_id: str
    ) -> None:
        """确保文件已索引（从 file_storage 拉取并上传/预处理）"""
        if not file_ids:
            return

        workspace = session_id or "default"
        client = self._get_client(session_id)

        # If workspace data was purged by upstream eviction, invalidate local index cache.
        if await self._workspace_appears_empty(client, session_id):
            prefix = f"{workspace}:"
            stale_keys = [key for key in self._indexed_files if key.startswith(prefix)]
            for key in stale_keys:
                self._indexed_files.discard(key)

        indexed_new = False
        for file_id in file_ids:
            cache_key = f"{workspace}:{user_id}:{file_id}"
            if cache_key in self._indexed_files:
                continue
            try:
                await self.add_document(file_id, user_id, session_id=session_id)
                self._indexed_files.add(cache_key)
                indexed_new = True
            except Exception as e:
                logger.warning(f"Failed to index file {file_id}: {e}")

        if indexed_new:
            try:
                await client.clear_cache(workspace=session_id)
            except Exception as e:
                logger.warning(f"Failed to clear LightRAG cache after indexing: {e}")

    async def _workspace_appears_empty(
        self,
        client: LightRAGRESTClient,
        session_id: Optional[str],
    ) -> bool:
        try:
            counts = await client.get_document_status_counts(workspace=session_id)
            if not isinstance(counts, dict):
                return False

            # Preferred shapes from LightRAG APIs.
            for key in ("total", "total_count", "count"):
                raw = counts.get(key)
                if isinstance(raw, int):
                    return raw <= 0

            # Fallback: sum all integer status counters.
            int_values = [v for v in counts.values() if isinstance(v, int)]
            if int_values:
                return sum(int_values) <= 0
        except Exception:
            # Fail-open: keep cache when status probe is unavailable.
            return False
        return False

    async def shutdown(self) -> None:
        await self.container.shutdown()

    async def _preprocess_and_insert(
        self,
        client: LightRAGRESTClient,
        filename: str,
        content_bytes: bytes,
        session_id: Optional[str],
        parser_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """预处理后插入文本，失败则回退上传原文件"""
        suffix = os.path.splitext(filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content_bytes)
            tmp_path = tmp.name

        try:
            payloads = await self._preprocess.preprocess(
                tmp_path,
                parser_params=parser_params,
            )
            if payloads:
                first_track = ""
                for payload in payloads:
                    result = await client.insert_text(
                        payload["content"],
                        workspace=session_id,
                        file_source=payload.get("file_source"),
                    )
                    if not first_track:
                        first_track = str(result.get("track_id") or "")
                if first_track:
                    await self._wait_track_ready(client, first_track, session_id)
                return first_track
        except Exception as e:
            logger.warning(f"Preprocess failed, fallback to upload: {e}")
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        guessed_content_type, _ = mimetypes.guess_type(filename)
        result = await client.upload_file_bytes(
            filename=filename,
            content=content_bytes,
            content_type=guessed_content_type or "application/octet-stream",
            workspace=session_id,
        )
        track_id = str(result.get("track_id") or "")
        if track_id:
            await self._wait_track_ready(client, track_id, session_id)
        return str(track_id or result.get("message") or "")

    async def _wait_track_ready(
        self,
        client: LightRAGRESTClient,
        track_id: str,
        session_id: Optional[str],
        timeout_seconds: float = 20.0,
    ) -> None:
        """Best-effort wait until LightRAG finishes ingesting a track."""
        if not track_id:
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        terminal_ok = {"completed", "done", "success", "processed", "finished"}
        terminal_fail = {"failed", "error", "cancelled"}

        while loop.time() < deadline:
            try:
                status = await client.get_track_status(track_id, workspace=session_id)
            except Exception:
                return

            status_text = str(status.get("status", "")).strip().lower()
            if status_text in terminal_ok:
                break
            if status_text in terminal_fail:
                raise RuntimeError(f"LightRAG track failed: {track_id}, status={status_text}")

            await asyncio.sleep(0.5)

        pipeline_deadline = loop.time() + max(5.0, timeout_seconds)
        while loop.time() < pipeline_deadline:
            try:
                pipeline = await client.get_pipeline_status(workspace=session_id)
            except Exception:
                return

            busy = bool(pipeline.get("busy", False))
            pending = bool(pipeline.get("request_pending", False))
            if not busy and not pending:
                return
            await asyncio.sleep(0.5)
