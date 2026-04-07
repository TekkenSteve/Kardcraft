# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# 依赖定义（缓存层）
COPY pyproject.toml uv.lock ./

# 使用 uv 安装依赖，带缓存加速
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --quiet

# 复制代码（独立层）
COPY src ./src

# ========== 运行时阶段 ==========
FROM python:3.11-slim-bookworm

WORKDIR /app

# Keep container runtime uid/gid aligned with common host user for bind-mounted workspace writes.
ARG APP_UID=1000
ARG APP_GID=1000

# 安全：非 root 用户
RUN groupadd -g "${APP_GID}" appuser && \
    useradd -u "${APP_UID}" -g "${APP_GID}" -d /app -s /bin/false appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

# 从 builder 复制虚拟环境
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

USER appuser

CMD ["python", "-m", "multitenant_lightrag"]
