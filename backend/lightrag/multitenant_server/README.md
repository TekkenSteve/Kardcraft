# LightRAG Multi-Tenant Gateway (MVP)

This service provides multi-workspace routing while preserving official LightRAG API paths.
For each workspace, it starts and reuses an official `lightrag-server` process.

## What it adds

- Route by `LIGHTRAG-WORKSPACE` request header.
- Per-workspace pooled clients (borrow/recycle model).
- Global and per-workspace inflight concurrency limits.
- Strict LRU workspace eviction when workspace count reaches upper bound.
- Per-workspace isolated runtime process with independent `working_dir` and `input_dir`.
- API compatibility by proxying `/{path}` requests.

## Endpoints

- `GET /gateway/health` : gateway health.
- `GET /gateway/pool/stats` : pool statistics.
- `GET /health` : proxied upstream runtime health for the resolved workspace.
- `ANY /{path:path}` : proxied to the resolved workspace runtime with original method/path/query/body.

## Environment variables

- `LIGHTRAG_MT_HOST` (default `0.0.0.0`)
- `LIGHTRAG_MT_PORT` (default `9621`)
- `LIGHTRAG_MT_LOG_LEVEL` (default `info`)
- `LIGHTRAG_UPSTREAM_TIMEOUT_SEC` (default `300`)
- `LIGHTRAG_PROCESS_CMD` (default `lightrag-server`)
- `LIGHTRAG_PROCESS_BIND_HOST` (default `127.0.0.1`)
- `LIGHTRAG_PROCESS_BASE_PORT` (default `29621`)
- `LIGHTRAG_PROCESS_STARTUP_TIMEOUT_SEC` (default `45`)
- `LIGHTRAG_WORKSPACES_ROOT` (default `/data/lightrag_workspaces`)
- `LIGHTRAG_TEMPLATE_ENV_FILE` (default `/app/.env.lightrag`)
- `LIGHTRAG_DEFAULT_WORKSPACE` (default `default`)
- `LIGHTRAG_ENFORCE_WORKSPACE_HEADER` (default `false`)
- `LIGHTRAG_POOL_SIZE_PER_WORKSPACE` (default `4`)
- `LIGHTRAG_MAX_WORKSPACE_COUNT` (default `200`)
- `LIGHTRAG_BORROW_TIMEOUT_SEC` (default `10`)
- `LIGHTRAG_GLOBAL_MAX_INFLIGHT` (default `128`)
- `LIGHTRAG_PER_WORKSPACE_MAX_INFLIGHT` (default `16`)
- `LIGHTRAG_API_KEY` (optional)
- `LIGHTRAG_PURGE_DATA_ON_EVICT` (default `true`)
- `LIGHTRAG_DELETE_WORKSPACE_DIR_ON_EVICT` (default `true`)

## Run locally

```bash
cd backend/lightrag/multitenant_server
python3 -m pip install -e .
# Ensure lightrag-server can read official config from this file
cp ../../../.env.lightrag ./.env.lightrag
python3 -m multitenant_lightrag
```

## Docker

```bash
cd backend/lightrag/multitenant_server
docker build -t lightrag-mt:dev .
docker run --rm -p 9621:9621 \
  -v $(pwd)/.env.lightrag:/app/.env.lightrag:ro \
  -v $(pwd)/../../../data/lightrag_workspaces:/data/lightrag_workspaces \
  lightrag-mt:dev
```

## Compose integration

Use one service for external API:
- `lightrag`: this gateway, mapped to host `:9621`.
- It launches official `lightrag-server` subprocesses per workspace using `.env.lightrag`.

## Verify Isolation

From repo root:

```bash
make verify-lightrag-isolation
```

Multi-round stability verification:

```bash
make verify-lightrag-isolation-stress
# or custom rounds:
LIGHTRAG_VERIFY_ROUNDS=20 make verify-lightrag-isolation-stress
```

Optional environment overrides:

```bash
LIGHTRAG_VERIFY_API_BASE=http://127.0.0.1:9621 \
LIGHTRAG_VERIFY_WORKSPACE_A=tenant_a \
LIGHTRAG_VERIFY_WORKSPACE_B=tenant_b \
make verify-lightrag-isolation
```

## Notes

This MVP keeps compatibility at API path level and adds runtime-per-workspace isolation.
