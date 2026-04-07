from __future__ import annotations

from contextlib import AbstractAsyncContextManager
import logging
from typing import Iterable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .pool import WorkspaceClientPool

logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

settings = Settings()
pool = WorkspaceClientPool(settings)
app = FastAPI(title="LightRAG Multi-Workspace Gateway", version="0.1.0")


def _filter_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        lowered = key.lower()
        if lowered in HOP_BY_HOP_HEADERS:
            continue
        out[key] = value
    return out


def _resolve_workspace(request: Request) -> str:
    raw = (request.headers.get("LIGHTRAG-WORKSPACE") or "").strip()
    if raw:
        return raw
    if settings.enforce_workspace_header:
        raise HTTPException(status_code=400, detail="LIGHTRAG-WORKSPACE header is required")
    return settings.default_workspace


def _is_stream_request(path: str) -> bool:
    return path.endswith("/query/stream")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await pool.close_all()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "lightrag-multitenant-gateway",
        "runtime_mode": "workspace_process",
        "process_cmd": settings.process_cmd,
        "workspaces_root": settings.workspaces_root,
    }


@app.get("/__pool/stats")
async def pool_stats() -> dict:
    return await pool.stats()


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(full_path: str, request: Request) -> Response:
    path = f"/{full_path}"

    if path in {"/health", "/__pool/stats"}:
        raise HTTPException(status_code=404, detail="Not found")

    workspace = _resolve_workspace(request)

    headers = _filter_headers(request.headers.items())
    headers["LIGHTRAG-WORKSPACE"] = workspace

    body = await request.body()
    params = list(request.query_params.multi_items())

    if _is_stream_request(path):
        return await _proxy_stream(request, workspace, path, params, headers, body)
    return await _proxy_once(request, workspace, path, params, headers, body)


async def _proxy_once(
    request: Request,
    workspace: str,
    path: str,
    params: list[tuple[str, str]],
    headers: dict[str, str],
    body: bytes,
) -> Response:
    try:
        async with pool.acquire(workspace) as client:
            upstream_response = await client.request(
                method=request.method,
                path=path,
                params=params,
                headers=headers,
                content=body,
            )
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="workspace client pool borrow timeout") from exc
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(status_code=502, detail=f"upstream request failed: {exc}") from exc

    response_headers = _filter_headers(upstream_response.headers.items())
    content_type = upstream_response.headers.get("content-type", "application/json")
    if content_type.startswith("application/json"):
        try:
            return JSONResponse(
                content=upstream_response.json(),
                status_code=upstream_response.status_code,
                headers=response_headers,
            )
        except Exception as exc:
            logger.warning(
                "failed to parse upstream json response method=%s path=%s status=%s err=%s",
                request.method,
                path,
                upstream_response.status_code,
                exc,
            )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=content_type,
    )


async def _proxy_stream(
    request: Request,
    workspace: str,
    path: str,
    params: list[tuple[str, str]],
    headers: dict[str, str],
    body: bytes,
) -> Response:
    acquire_cm: AbstractAsyncContextManager = pool.acquire(workspace)
    entered_pool = False
    try:
        client = await acquire_cm.__aenter__()
        entered_pool = True
        stream_cm = client.request_stream(
            method=request.method,
            path=path,
            params=params,
            headers=headers,
            content=body,
        )
        upstream_response = await stream_cm.__aenter__()
    except TimeoutError as exc:
        if entered_pool:
            await acquire_cm.__aexit__(type(exc), exc, exc.__traceback__)
        raise HTTPException(status_code=503, detail="workspace client pool borrow timeout") from exc
    except Exception as exc:
        if entered_pool:
            await acquire_cm.__aexit__(type(exc), exc, exc.__traceback__)
        raise HTTPException(status_code=502, detail=f"upstream stream request failed: {exc}") from exc

    response_headers = _filter_headers(upstream_response.headers.items())
    content_type = upstream_response.headers.get("content-type", "application/octet-stream")

    async def body_iter():
        exc_info = (None, None, None)
        try:
            async for chunk in upstream_response.aiter_raw():
                if chunk:
                    yield chunk
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
            raise
        finally:
            await stream_cm.__aexit__(*exc_info)
            await acquire_cm.__aexit__(*exc_info)

    return StreamingResponse(
        body_iter(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=content_type,
    )
