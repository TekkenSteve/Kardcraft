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


class TrackCancelledError(RuntimeError):
    """Raised when LightRAG reports a cancelled track."""


class FileIndexingError(RuntimeError):
    """Raised when one or more requested files cannot be indexed."""

    def __init__(self, failures: Dict[str, str]):
        self.failures = dict(failures)
        details = "; ".join(f"{file_id}: {error}" for file_id, error in failures.items())
        super().__init__(f"failed to index requested files: {details}")


def _normalize_filename(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    basename = os.path.basename(normalized)
    return basename.casefold()


def _extract_documents(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    statuses = payload.get("statuses")
    if isinstance(statuses, dict):
        flattened: List[Dict[str, Any]] = []
        for docs in statuses.values():
            if not isinstance(docs, list):
                continue
            flattened.extend([x for x in docs if isinstance(x, dict)])
        if flattened:
            return flattened
    for key in ("documents", "items", "data", "docs", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = _extract_documents(value)
            if nested:
                return nested
    dict_values = [x for x in payload.values() if isinstance(x, dict)]
    if dict_values and len(dict_values) >= max(2, len(payload) // 2):
        return dict_values
    return []


def _extract_summary_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        parts: List[str] = []
        for item in payload:
            text = _extract_summary_text(item).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
        return ""
    if not isinstance(payload, dict):
        return ""
    documents = payload.get("documents")
    if isinstance(documents, list):
        parts = []
        for item in documents:
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("content_summary")
                or item.get("summary")
                or item.get("document_summary")
                or ""
            ).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
    for key in ("summary", "content_summary", "doc_summary", "document_summary", "file_summary"):
        text = _extract_summary_text(payload.get(key))
        if text:
            return text
    for key, value in payload.items():
        if "summary" not in str(key).lower():
            continue
        text = _extract_summary_text(value)
        if text:
            return text
    for key in ("data", "document", "doc", "result", "payload"):
        text = _extract_summary_text(payload.get(key))
        if text:
            return text
    return ""


def _extract_track_document_summary(
    track_payload: Any,
    *,
    preferred_doc_id: str,
    preferred_filename: str,
) -> str:
    if not isinstance(track_payload, dict):
        return ""
    documents = track_payload.get("documents")
    if not isinstance(documents, list):
        return ""

    preferred_id = str(preferred_doc_id or "").strip()
    preferred_name = _normalize_filename(preferred_filename)
    fallback = ""

    for item in documents:
        if not isinstance(item, dict):
            continue
        summary = str(
            item.get("content_summary")
            or item.get("summary")
            or item.get("document_summary")
            or ""
        ).strip()
        if not summary:
            continue
        if not fallback:
            fallback = summary

        doc_id = str(item.get("id") or item.get("doc_id") or item.get("document_id") or "").strip()
        if preferred_id and doc_id and doc_id == preferred_id:
            return summary

        file_path = _normalize_filename(str(item.get("file_path") or item.get("filename") or ""))
        if preferred_name and file_path and file_path == preferred_name:
            return summary

    return fallback


def _find_doc_by_filename(
    documents: List[Dict[str, Any]],
    *,
    target_filename: str,
    file_id: str,
) -> Dict[str, Any] | None:
    target_norm = _normalize_filename(target_filename)
    file_id_norm = str(file_id or "").strip()
    best: Dict[str, Any] | None = None
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("id") or doc.get("doc_id") or doc.get("document_id") or "").strip()
        if file_id_norm and doc_id and doc_id == file_id_norm:
            return doc
        candidates = [
            doc.get("file_name"),
            doc.get("filename"),
            doc.get("original_filename"),
            doc.get("name"),
            doc.get("title"),
            doc.get("file_path"),
            doc.get("source"),
        ]
        for candidate in candidates:
            normalized = _normalize_filename(str(candidate or ""))
            if normalized and normalized == target_norm:
                return doc
            if not best and target_norm and normalized.endswith(target_norm):
                best = doc
    return best


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
        self._file_title_cache: Dict[str, str] = {}

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
        self._record_file_title(session_id=session_id, user_id=user_id, file_id=file_id, title=filename)

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
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Answer:
        """Query LightRAG (workspace isolated by session_id)"""
        if not self._initialized:
            await self.initialize()

        if file_ids and user_id:
            await self._ensure_files_indexed(session_id, file_ids, user_id)

        client = self._get_client(session_id)
        rewrite_hints = await self._build_rewrite_hints(
            session_id=session_id,
            user_id=user_id,
            file_ids=file_ids,
        )
        return await self._query_pipeline.query(
            client,
            question,
            session_id=session_id,
            mode=mode,
            modes=modes,
            top_k=top_k,
            include_references=True,
            conversation_history=conversation_history,
            rewrite_hints=rewrite_hints,
        )

    async def get_file_track_summaries(
        self,
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        file_ids: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """按 file_ids 匹配 LightRAG 文档并通过 track_status 提取 summary。"""
        if not session_id or not user_id or not file_ids:
            return []
        normalized_file_ids = [str(x).strip() for x in file_ids if str(x).strip()]
        if not normalized_file_ids:
            return []
        if not self._initialized:
            await self.initialize()

        await self._ensure_files_indexed(session_id, normalized_file_ids, user_id)
        workspace = session_id or "default"
        targets: List[Dict[str, str]] = []
        for file_id in normalized_file_ids:
            cache_key = f"{workspace}:{user_id}:{file_id}"
            filename = str(self._file_title_cache.get(cache_key) or file_id).strip()
            targets.append({"file_id": file_id, "filename": filename})
        if not targets:
            return []

        client = self._get_client(session_id)
        docs_payload = await client.get_documents_statuses(workspace=session_id)
        documents = _extract_documents(docs_payload)
        if not documents:
            return []

        summaries: List[Dict[str, Any]] = []
        for target in targets:
            file_id = str(target.get("file_id") or "").strip()
            filename = str(target.get("filename") or file_id).strip()
            doc = _find_doc_by_filename(documents, target_filename=filename, file_id=file_id)
            if not isinstance(doc, dict):
                continue
            preferred_doc_id = str(doc.get("id") or doc.get("doc_id") or doc.get("document_id") or "").strip()

            track_ref = str(
                doc.get("track_id")
                or doc.get("id")
                or doc.get("doc_id")
                or doc.get("document_id")
                or ""
            ).strip()
            if not track_ref:
                continue

            summary_text = ""
            try:
                track_status = await client.get_track_status(track_ref, workspace=session_id)
                summary_text = _extract_track_document_summary(
                    track_status,
                    preferred_doc_id=preferred_doc_id,
                    preferred_filename=filename,
                )
            except Exception as exc:
                logger.warning(
                    "failed to fetch lightrag track summary",
                    file_id=file_id,
                    filename=filename,
                    track_ref=track_ref,
                    error=str(exc),
                )

            if not summary_text:
                summary_text = _extract_summary_text(doc)
            if not summary_text:
                continue

            summaries.append(
                {
                    "file_id": file_id,
                    "filename": filename,
                    "track_ref": track_ref,
                    "summary": summary_text,
                }
            )
        return summaries

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
            stale_title_keys = [key for key in self._file_title_cache if key.startswith(prefix)]
            for key in stale_title_keys:
                self._file_title_cache.pop(key, None)

        indexed_new = False
        failures: Dict[str, str] = {}
        for file_id in file_ids:
            cache_key = f"{workspace}:{user_id}:{file_id}"
            if cache_key in self._indexed_files:
                continue
            try:
                await self.add_document(file_id, user_id, session_id=session_id)
                self._indexed_files.add(cache_key)
                indexed_new = True
            except Exception as e:
                failures[file_id] = str(e)
                logger.error(
                    "failed to index requested file",
                    file_id=file_id,
                    workspace=workspace,
                    error=str(e),
                )

        if indexed_new:
            try:
                await client.clear_cache(workspace=session_id)
            except Exception as e:
                logger.warning(f"Failed to clear LightRAG cache after indexing: {e}")

        if failures:
            raise FileIndexingError(failures)

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
        terminal_fail = {"failed", "error"}
        terminal_cancelled = {"cancelled", "canceled"}

        while loop.time() < deadline:
            try:
                status = await client.get_track_status(track_id, workspace=session_id)
            except Exception:
                return

            status_text = str(status.get("status", "")).strip().lower()
            if status_text in terminal_ok:
                break
            if status_text in terminal_cancelled:
                raise TrackCancelledError(
                    f"LightRAG track cancelled: {track_id}, status={status_text}"
                )
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

    def _record_file_title(
        self,
        *,
        session_id: Optional[str],
        user_id: str,
        file_id: str,
        title: str,
    ) -> None:
        workspace = session_id or "default"
        normalized = str(title or "").strip()
        if not normalized:
            return
        key = f"{workspace}:{user_id}:{file_id}"
        self._file_title_cache[key] = normalized

    async def _build_rewrite_hints(
        self,
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        file_ids: Optional[List[str]],
    ) -> Dict[str, Any]:
        workspace = session_id or "default"
        hints: Dict[str, Any] = {"workspace": workspace}
        if not user_id or not file_ids:
            return hints

        titles: List[str] = []
        seen = set()
        for file_id in file_ids:
            key = f"{workspace}:{user_id}:{file_id}"
            title = str(self._file_title_cache.get(key) or "").strip()
            if not title:
                continue
            folded = title.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            titles.append(title)

        if titles:
            hints["uploaded_file_titles"] = titles
        return hints
