# syntax=docker/dockerfile:1.7
# ============================================================================
# Kardcraft Agent Workflow Dockerfile (Optimized)
# ============================================================================

# 阶段1: 依赖安装 (使用 uv 官方镜像)
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# 仅复制依赖定义 - 最大化缓存命中率
COPY pyproject.toml uv.lock ./
# 依赖定义（缓存层）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --quiet
# 代码（独立层，变动不影响依赖）
COPY src/ ./src/

# 阶段2: 运行时 (最小化基础镜像)
# FROM python:3.11-slim-bookworm AS runtime
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS runtime

WORKDIR /app

# 安全: 非 root 用户
RUN groupadd -r kardcraft && \
    useradd -r -g kardcraft -d /app -s /bin/false kardcraft && \
    apt-get update && \
    apt-get install -y --no-install-recommends libpq5 ca-certificates libxcb1 && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* && \
    mkdir -p /app/storage /app/tmp /app/logs && \
    chown -R kardcraft:kardcraft /app

# 从 builder 复制虚拟环境 (而非全局 site-packages)
COPY --from=builder --chown=kardcraft:kardcraft /app/.venv /app/.venv
COPY --from=builder --chown=kardcraft:kardcraft /app/src ./src
# COPY --chown=kardcraft:kardcraft .env.example ./

# 使用虚拟环境
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

USER kardcraft

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import kardcraft" || exit 1

CMD ["python", "-m", "kardcraft.temporal.worker"]
