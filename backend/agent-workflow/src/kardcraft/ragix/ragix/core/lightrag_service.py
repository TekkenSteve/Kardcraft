import asyncio  
import httpx  
import json  
from typing import Dict, Any, Optional, Literal, List, Union, AsyncGenerator
from pathlib import Path  
from .config import LightRAGServerConfig
from kardcraft.utils.logger import logger
  
class LightRAGRESTClient:  
    """完善的 LightRAG REST API 客户端"""  
      
    def __init__(self, config: LightRAGServerConfig):  
        self.config = config  
        self._client: Optional[httpx.AsyncClient] = None  
        self._initialized = False  
          
    async def initialize(self) -> bool:  
        """初始化客户端"""  
        if self._initialized:  
            return True  
              
        try:  
            headers = {}  
            if self.config.api_key:  
                headers["X-API-Key"] = self.config.api_key  
                  
            self._client = httpx.AsyncClient(  
                base_url=self.config.base_url,  
                headers=headers,  
                timeout=self.config.timeout  
            )  
              
            # Prefer gateway health for multitenant gateway deployments.
            # Fallback to /health for direct lightrag-server deployments.
            gateway_resp = await self._client.get("/gateway/health")
            if gateway_resp.status_code == 404:
                fallback_resp = await self._client.get("/health")
                fallback_resp.raise_for_status()
            else:
                gateway_resp.raise_for_status()
            self._initialized = True  
            logger.info(f"Connected to LightRAG server at {self.config.base_url}")  
            return True  
              
        except Exception as e:  
            logger.error(f"Failed to connect to LightRAG server: {e}")  
            return False  

    async def get_health(self) -> Dict[str, Any]:
        """Get runtime health status from /health."""
        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError("Client not initialized")

        assert self._client is not None
        response = await self._client.get("/health")
        response.raise_for_status()
        return response.json()

    async def get_gateway_health(self) -> Dict[str, Any]:
        """Get gateway health status from /gateway/health."""
        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError("Client not initialized")

        assert self._client is not None
        response = await self._client.get("/gateway/health")
        response.raise_for_status()
        return response.json()

    async def get_gateway_pool_stats(self) -> Dict[str, Any]:
        """Get gateway pool stats from /gateway/pool/stats."""
        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError("Client not initialized")

        assert self._client is not None
        response = await self._client.get("/gateway/pool/stats")
        response.raise_for_status()
        return response.json()
      
    async def _make_request(  
        self,   
        method: str,   
        endpoint: str,   
        workspace: Optional[str] = None,  
        **kwargs  
    ) -> Dict[str, Any]:  
        """发送HTTP请求"""  
        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError("Client not initialized")
              
        assert self._client is not None

        # 添加工作区头  
        if workspace:  
            headers = kwargs.get("headers", {})  
            headers["LIGHTRAG-WORKSPACE"] = workspace  
            kwargs["headers"] = headers  

        # Multipart uploads must not use JSON content-type; let httpx set boundary.
        if "files" in kwargs:
            headers = kwargs.get("headers", {})
            if isinstance(headers, dict):
                headers.pop("Content-Type", None)
                headers.pop("content-type", None)
                kwargs["headers"] = headers
              
        for attempt in range(self.config.max_retries):  
            try:  
                response = await self._client.request(method, endpoint, **kwargs)  
                response.raise_for_status()  
                return response.json()  
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code if e.response is not None else None
                detail = ""
                try:
                    detail = e.response.text if e.response is not None else ""
                except Exception:
                    detail = ""
                if status_code is not None and 400 <= status_code < 500:
                    raise RuntimeError(
                        f"LightRAG request failed: {method} {endpoint} "
                        f"status={status_code} detail={detail[:500]}"
                    ) from e
                if attempt == self.config.max_retries - 1:
                    raise RuntimeError(
                        f"LightRAG request failed after retries: {method} {endpoint} "
                        f"status={status_code} detail={detail[:500]}"
                    ) from e
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))
            except Exception as e:  
                if attempt == self.config.max_retries - 1:  
                    raise  # re-raise original exception type
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

    # ==================== 文档管理 API ====================  
      
    async def upload_file(
        self,
        file_path: Union[str, Path],
        workspace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """上传单个文件（/documents/upload）"""
        file_path = Path(file_path)

        if metadata:
            logger.warning("metadata is not supported by LightRAG /documents/upload and will be ignored")

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            return await self._make_request(
                "POST",
                "/documents/upload",
                workspace=workspace,
                files=files,
            )
      
    async def upload_file_bytes(
        self,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """上传字节内容为文件（/documents/upload）"""
        files = {"file": (filename, content, content_type)}
        return await self._make_request(
            "POST",
            "/documents/upload",
            workspace=workspace,
            files=files,
        )
        
    async def upload_files(
        self,
        file_paths: List[Union[str, Path]],
        workspace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """批量上传文件（逐个调用 /documents/upload）"""
        return [await self.upload_file(file_path, workspace=workspace) for file_path in file_paths]
      
    async def insert_text(
        self,
        content: str,
        workspace: Optional[str] = None,
        file_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """插入文本内容（/documents/text）"""
        payload = {"text": content}
        if file_source is not None:
            payload["file_source"] = file_source

        return await self._make_request(
            "POST",
            "/documents/text",
            workspace=workspace,
            json=payload,
        )
      
    async def insert_texts(  
        self,   
        texts: List[str],   
        workspace: Optional[str] = None,  
        file_sources: Optional[List[str]] = None  
    ) -> Dict[str, Any]:  
        """批量插入文本"""  
        payload = {"texts": texts}  
        if file_sources:  
            payload["file_sources"] = file_sources  
              
        return await self._make_request(  
            "POST",  
            "/documents/texts",  
            workspace=workspace,  
            json=payload  
        )  
      
    async def scan_documents(self, workspace: Optional[str] = None) -> Dict[str, Any]:  
        """扫描输入目录中的文档"""  
        return await self._make_request("POST", "/documents/scan", workspace=workspace)  
      
    async def get_documents(
        self,
        workspace: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        status_filter: Optional[str] = None,
        sort_field: str = "updated_at",
        sort_direction: Literal["asc", "desc"] = "desc",
    ) -> Dict[str, Any]:
        """获取文档列表（分页，/documents/paginated）"""
        payload = {
            "page": page,
            "page_size": page_size,
            "sort_field": sort_field,
            "sort_direction": sort_direction,
        }
        if status_filter is not None:
            payload["status_filter"] = status_filter

        return await self._make_request(
            "POST",
            "/documents/paginated",
            workspace=workspace,
            json=payload,
        )

    async def get_documents_statuses(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """获取文档状态集合（/documents, deprecated by server）"""
        return await self._make_request("GET", "/documents", workspace=workspace)

    async def get_document_status_counts(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """获取文档状态计数（/documents/status_counts）"""
        return await self._make_request("GET", "/documents/status_counts", workspace=workspace)

    async def get_track_status(self, track_id: str, workspace: Optional[str] = None) -> Dict[str, Any]:
        """获取上传/插入的处理进度（/documents/track_status/{track_id}）"""
        return await self._make_request(
            "GET",
            f"/documents/track_status/{track_id}",
            workspace=workspace,
        )
      
    async def delete_documents(
        self,
        doc_ids: List[str],
        workspace: Optional[str] = None,
        delete_file: bool = False,
        delete_llm_cache: bool = False,
    ) -> Dict[str, Any]:
        """删除指定文档（/documents/delete_document）"""
        payload = {
            "doc_ids": doc_ids,
            "delete_file": delete_file,
            "delete_llm_cache": delete_llm_cache,
        }
        return await self._make_request(
            "DELETE",
            "/documents/delete_document",
            workspace=workspace,
            json=payload,
        )
      
    async def clear_all_documents(
        self,
        workspace: Optional[str] = None,
        clear_llm_cache: bool = False,
    ) -> Dict[str, Any]:
        """清除所有文档（/documents）"""
        if clear_llm_cache:
            await self.clear_cache(workspace=workspace)

        return await self._make_request("DELETE", "/documents", workspace=workspace)

    async def clear_cache(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """清理 LLM 缓存（/documents/clear_cache）"""
        return await self._make_request("POST", "/documents/clear_cache", workspace=workspace, json={})
      
    async def get_pipeline_status(self, workspace: Optional[str] = None) -> Dict[str, Any]:  
        """获取文档处理管道状态"""  
        return await self._make_request("GET", "/documents/pipeline_status", workspace=workspace)  
      
    async def cancel_pipeline(self, workspace: Optional[str] = None) -> Dict[str, Any]:  
        """取消文档处理管道"""  
        return await self._make_request("POST", "/documents/cancel_pipeline", workspace=workspace)  
      
    async def reprocess_failed_documents(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """重新处理失败的文档（/documents/reprocess_failed）"""
        return await self._make_request("POST", "/documents/reprocess_failed", workspace=workspace)
      
    # ==================== 查询 API ====================  
      
    async def query(  
        self,  
        question: str,  
        workspace: Optional[str] = None,  
        mode: Literal["naive", "local", "global", "hybrid", "mix", "bypass"] = "mix",  
        include_references: bool = True,  
        include_chunk_content: bool = False,  
        enable_rerank: Optional[bool] = None,  
        top_k: int = 60,  
        chunk_top_k: int = 20,  
        **kwargs  
    ) -> Dict[str, Any]:  
        """查询LightRAG"""  
        payload = {  
            "query": question,  
            "mode": mode,  
            "include_references": include_references,  
            "include_chunk_content": include_chunk_content,  
            "top_k": top_k,  
            "chunk_top_k": chunk_top_k,  
            **kwargs  
        }  
        if enable_rerank is not None:
            payload["enable_rerank"] = enable_rerank
        return await self._make_request("POST", "/query", workspace=workspace, json=payload)  
      
    async def query_stream_events(  
        self,  
        question: str,  
        workspace: Optional[str] = None,  
        mode: Literal["naive", "local", "global", "hybrid", "mix", "bypass"] = "mix",  
        include_references: bool = True,  
        enable_rerank: Optional[bool] = None,  
        **kwargs  
    ) -> AsyncGenerator[Dict[str, Any], None]:  
        """流式查询（返回完整事件对象）"""  
        payload = {  
            "query": question,  
            "mode": mode,  
            "include_references": include_references,  
            "stream": True,  
            **kwargs  
        }  
        if enable_rerank is not None:
            payload["enable_rerank"] = enable_rerank

        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError("Client not initialized")

        assert self._client is not None

        async with self._client.stream(  
            "POST",  
            "/query/stream",  
            json=payload,  
            headers={"LIGHTRAG-WORKSPACE": workspace} if workspace else {}  
        ) as response:  
            response.raise_for_status()  
            async for line in response.aiter_lines():  
                if not line.strip():  
                    continue  
                data = json.loads(line)  
                if "error" in data:  
                    raise RuntimeError(data["error"])  
                yield data  

    async def query_stream(  
        self,  
        question: str,  
        workspace: Optional[str] = None,  
        mode: Literal["naive", "local", "global", "hybrid", "mix", "bypass"] = "mix",  
        include_references: bool = True,  
        enable_rerank: Optional[bool] = None,  
        **kwargs  
    ) -> AsyncGenerator[str, None]:  
        """流式查询（仅返回 response 片段）"""  
        async for event in self.query_stream_events(  
            question,  
            workspace=workspace,  
            mode=mode,  
            include_references=include_references,  
            enable_rerank=enable_rerank,  
            **kwargs,  
        ):  
            if "response" in event:  
                yield event["response"]  
      
    async def query_data(  
        self,  
        question: str,  
        workspace: Optional[str] = None,  
        mode: Literal["naive", "local", "global", "hybrid", "mix", "bypass"] = "mix",  
        **kwargs  
    ) -> Dict[str, Any]:  
        """获取结构化查询数据（实体、关系、文本块）"""  
        payload = {  
            "query": question,  
            "mode": mode,  
            **kwargs  
        }  
        return await self._make_request("POST", "/query/data", workspace=workspace, json=payload)  
      
    # ==================== 图操作 API ====================  
      
    async def get_graph_labels(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """获取图标签列表（/graph/label/list）"""
        return await self._make_request("GET", "/graph/label/list", workspace=workspace)

    async def get_popular_labels(
        self,
        limit: int = 300,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取热门标签（/graph/label/popular）"""
        params = {"limit": limit}
        return await self._make_request(
            "GET",
            "/graph/label/popular",
            workspace=workspace,
            params=params,
        )

    async def search_labels(
        self,
        query: str,
        limit: int = 50,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """搜索标签（/graph/label/search）"""
        params = {"q": query, "limit": limit}
        return await self._make_request(
            "GET",
            "/graph/label/search",
            workspace=workspace,
            params=params,
        )

    async def get_knowledge_graph(
        self,
        label: str,
        max_depth: int = 3,
        max_nodes: int = 1000,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取知识图谱子图（/graphs）"""
        params = {"label": label, "max_depth": max_depth, "max_nodes": max_nodes}
        return await self._make_request(
            "GET",
            "/graphs",
            workspace=workspace,
            params=params,
        )

    async def check_entity_exists(self, name: str, workspace: Optional[str] = None) -> Dict[str, Any]:
        """检查实体是否存在（/graph/entity/exists）"""
        params = {"name": name}
        return await self._make_request(
            "GET",
            "/graph/entity/exists",
            workspace=workspace,
            params=params,
        )
      
    async def create_entity(
        self,
        entity_name: str,
        entity_data: Dict[str, Any],
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建实体（/graph/entity/create）"""
        payload = {
            "entity_name": entity_name,
            "entity_data": entity_data,
        }
        return await self._make_request(
            "POST",
            "/graph/entity/create",
            workspace=workspace,
            json=payload,
        )
      
    async def update_entity(
        self,
        entity_name: str,
        updated_data: Dict[str, Any],
        allow_rename: bool = False,
        allow_merge: bool = False,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新实体（/graph/entity/edit）"""
        payload = {
            "entity_name": entity_name,
            "updated_data": updated_data,
            "allow_rename": allow_rename,
            "allow_merge": allow_merge,
        }
        return await self._make_request(
            "POST",
            "/graph/entity/edit",
            workspace=workspace,
            json=payload,
        )
      
    async def delete_entity(
        self,
        entity_name: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """删除实体（/documents/delete_entity）"""
        payload = {"entity_name": entity_name}
        return await self._make_request(
            "DELETE",
            "/documents/delete_entity",
            workspace=workspace,
            json=payload,
        )
      
    async def create_relation(
        self,
        source_entity: str,
        target_entity: str,
        relation_data: Dict[str, Any],
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建关系（/graph/relation/create）"""
        payload = {
            "source_entity": source_entity,
            "target_entity": target_entity,
            "relation_data": relation_data,
        }
        return await self._make_request(
            "POST",
            "/graph/relation/create",
            workspace=workspace,
            json=payload,
        )
      
    async def update_relation(
        self,
        source_id: str,
        target_id: str,
        updated_data: Dict[str, Any],
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新关系（/graph/relation/edit）"""
        payload = {
            "source_id": source_id,
            "target_id": target_id,
            "updated_data": updated_data,
        }
        return await self._make_request(
            "POST",
            "/graph/relation/edit",
            workspace=workspace,
            json=payload,
        )
      
    async def delete_relation(
        self,
        source_entity: str,
        target_entity: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """删除关系（/documents/delete_relation）"""
        payload = {"source_entity": source_entity, "target_entity": target_entity}
        return await self._make_request(
            "DELETE",
            "/documents/delete_relation",
            workspace=workspace,
            json=payload,
        )

    async def merge_entities(
        self,
        entities_to_change: List[str],
        entity_to_change_into: str,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """合并实体（/graph/entities/merge）"""
        payload = {
            "entities_to_change": entities_to_change,
            "entity_to_change_into": entity_to_change_into,
        }
        return await self._make_request(
            "POST",
            "/graph/entities/merge",
            workspace=workspace,
            json=payload,
        )
      
    # ==================== 工作区管理（仅通过 Header 隔离） ====================  
      
    async def create_workspace(self, workspace: str) -> Dict[str, Any]:  
        """创建新工作区（通过插入测试文档触发初始化）"""  
        try:  
            await self.insert_text("Workspace initialization", workspace=workspace)  
            return {"status": "success", "workspace": workspace}  
        except Exception as e:  
            return {"status": "error", "message": str(e)}  
      
    async def drop_workspace(self, workspace: str) -> Dict[str, Any]:
        """完全删除工作区数据（DELETE /documents，触发服务器 drop）"""
        try:
            await self.clear_cache(workspace=workspace)
            return await self._make_request("DELETE", "/documents", workspace=workspace)
        except Exception as e:
            return {"status": "error", "message": f"Cleanup failed: {str(e)}"}
      
    # ==================== 系统管理 ====================  
      
    async def get_server_status(self) -> Dict[str, Any]:  
        """获取服务器状态"""  
        return await self._make_request("GET", "/status")  
      
    async def get_server_config(self) -> Dict[str, Any]:  
        """获取服务器配置"""  
        return await self._make_request("GET", "/config")  
      
    async def shutdown(self):  
        """关闭客户端"""  
        if self._client:  
            await self._client.aclose()  
            self._initialized = False  
  
  
class LightRAGServiceManager:  
    """多实例LightRAG服务管理器"""  
      
    def __init__(self, base_config: LightRAGServerConfig):  
        self.base_config = base_config  
        self._instances: Dict[str, LightRAGRESTClient] = {}  

    def has_any_instance(self) -> bool:
        return bool(self._instances)
          
    def get_instance(self, workspace: str) -> LightRAGRESTClient:  
        """获取指定工作区的客户端实例"""  
        if workspace not in self._instances:  
            # 为每个工作区创建独立的客户端  
            config = LightRAGServerConfig(**self.base_config.model_dump())  
            self._instances[workspace] = LightRAGRESTClient(config)  
          
        return self._instances[workspace]  
      
    async def initialize_all(self) -> Dict[str, bool]:  
        """初始化所有实例"""  
        results = {}  
        for workspace, client in self._instances.items():  
            results[workspace] = await client.initialize()  
        return results  
      
    async def shutdown_all(self):  
        """关闭所有实例"""  
        for workspace, client in self._instances.items():  
            await client.shutdown()  
        self._instances.clear()  
